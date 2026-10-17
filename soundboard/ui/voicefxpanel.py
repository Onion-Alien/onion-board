"""The Voice tab's voice changer card: `VoiceFxPanel`, its effect rows
(`EffectRow`, `ParamSlider`) and voice tiles.

It follows panel.py's pattern: it owns its widgets and emits plain dicts
(`changed`) that the main window stores in the config.
"""
from __future__ import annotations

import functools
import html
import random
import threading
from collections.abc import Callable

import numpy as np

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter
from PySide6.QtWidgets import (QBoxLayout, QButtonGroup, QCheckBox, QDialog, QFrame, QGridLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu,
                               QMessageBox, QPushButton, QScrollArea, QSizePolicy,
                               QSlider, QStyle, QStyleOptionSlider, QToolButton,
                               QVBoxLayout, QWidget)
from shiboken6 import isValid as qt_valid

from soundboard import errors, savedvoices, theme, usage, voicefx
from soundboard.speech import aipreview
from soundboard.ui import art, busy, icons
from soundboard.ui.aivoicebrowser import HEAR, MAKING, hear_button
from soundboard.ui.widgets import take_out
from soundboard.ui.panel import (Flow, UndoBar, ViewToggle, hint_label, reset_button, section_label,
                                 steady_number)
from soundboard.wheelguard import no_wheel
from soundboard.i18n import _, ngettext
from soundboard.ui.pixels import snap_to_pixels


CUSTOM = "Custom"
TILE_ART = 48     # px: a voice card's picture (when there is one, see ui/art.py)
TILE_MIN_W = 124  # px: a voice card at its narrowest (the row holds as many as fit)
TILE_GAP = 8      # px: between voice cards
LIST_MIN_W = 190  # px: a voice row at its narrowest (the list view)
LIST_ART = 30     # px: a voice row's picture
MAX_COLS = 12     # voice cards a row, at most
PICKED_ART = 32   # px: the picked voice's picture, under the cards


def default_fx_spec() -> dict:
    return {"enabled": False, "preset": CUSTOM, "effects": {}}


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


# the app's own line icons (ui/icons.py), like everywhere else
FX_ICONS = {"cleanup": "shield", "pitch": "mic", "growl": "wave", "robot": "keyboard",
            "compressor": "volume", "tone": "sliders", "radio": "radio", "distortion": "live",
            "shout": "speech", "helmet": "voice", "chorus": "shuffle", "echo": "history",
            "reverb": "headphones", "polish": "star", "harmony": "music", "ringmod": "wave",
            "backdrop": "sounds",
            "flanger": "reload", "wobble": "ear"}
# the Voice tab's "Edit voice" window's top and the effect cards' groups;
# an effect from an add-on goes under Add-ons
HERO = ("pitch", "cleanup")
HERO_TITLES = {"pitch": _("Pitch & voice")}
GROUPS = ((_("Change the voice"), ("harmony", "growl", "robot", "ringmod")),
          (_("Character"), ("compressor", "tone", "radio", "distortion", "shout", "helmet",
                            "polish")),
          (_("Room"), ("chorus", "flanger", "wobble", "echo", "reverb", "backdrop")))
ADDON_GROUP = _("Add-ons")
# your own setting, not part of a voice: picking or saving a voice leaves it as it is
# yours, not the voice's: picking a voice leaves them as they are (your mic clean-up,
# the Background's sounds); with the Effects pop-up's extras, they're "on top"
KEEP = frozenset({"cleanup", "backdrop"})


def on_top(etype: str) -> bool:
    """Not part of the voice: kept when you pick another one, never saved with it."""
    cls = voicefx.REGISTRY.get(etype)
    return etype in KEEP or bool(cls is not None and cls.extra)


class EffectRow(QFrame):
    """One effect as a card: icon, name, an on/off switch, what it does, and its
    settings while it's on. `hero` (Pitch, Clean up my mic): the settings always
    show, and moving one switches the effect on. Its arrow folds it down to just
    its title line (`folded_changed`)."""
    changed = Signal()
    folded_changed = Signal(bool)
    reshaped = Signal()   # taller or shorter: switched on or off, folded or opened

    def __init__(self, cls: type[voicefx.Effect], cfg: dict, hero: bool = False):
        super().__init__()
        self.cls = cls
        self.hero = hero
        self.setObjectName("fxcard")
        self.setProperty("hero", hero)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)   # so [on] / [fresh] can paint
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(8)
        icon = QLabel()
        icons.set_label_icon(icon, FX_ICONS.get(cls.type, "sliders"), "accent_hi", size=16)
        icon.setObjectName("fxicon")
        head.addWidget(icon)
        title = QLabel(HERO_TITLES.get(cls.type) or voicefx.shown(cls.name))
        title.setObjectName("fxname")
        head.addWidget(title)
        head.addStretch(1)
        self.btn_reset = reset_button(_("Put {effect}'s settings back to how they start",
                                        effect=voicefx.shown(cls.name)), hover=False)
        self.btn_reset.clicked.connect(self.reset)
        head.addWidget(self.btn_reset)
        self.chk = Switch(_("Turn {effect} on or off", effect=voicefx.shown(cls.name)),
                          hover=False)
        self.chk.setChecked(bool(cfg.get("on")))
        head.addWidget(self.chk)
        self.arrow = QPushButton()
        self.arrow.setObjectName("fold")
        self.arrow.setProperty("icononly", True)   # centred, no text padding
        self.arrow.setFocusPolicy(Qt.FocusPolicy.TabFocus)     # a click leaves no focus box on it
        self.arrow.setFixedSize(24, 24)
        self.arrow.setCursor(Qt.CursorShape.PointingHandCursor)
        self.arrow.clicked.connect(lambda: self.set_folded(not self._folded, asked=True))
        head.addWidget(self.arrow)
        self._folded = False
        v.addLayout(head)
        self.desc = hint_label(voicefx.shown(cls.description))
        self.desc.setObjectName("fxdesc")
        v.addWidget(self.desc)
        self.err = hint_label("")
        theme.set_tone(self.err, "error")
        self.err.hide()
        v.addWidget(self.err)
        self.body = QWidget()
        grid = QGridLayout(self.body)
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        self.sliders = []
        self._fill(grid, cfg)
        v.addWidget(self.body)
        self.chk.toggled.connect(self._toggled)
        self._shown: tuple | None = None   # the (on, folded) the card last showed
        self._paint_arrow()
        self._show()

    def _fill(self, grid: QGridLayout, cfg: dict):
        """The settings under the title: a slider (or switch) per parameter. An effect
        with settings of its own shape (the Background) overrides this."""
        cols = 2 if self.hero and len(self.cls.params) > 2 else 1
        for i, q in enumerate(self.cls.params):
            s = ParamSlider(q, cfg.get(q.key, q.default), compact=False)
            s.changed.connect(self._slid)
            grid.addWidget(s, i // cols, i % cols)
            self.sliders.append(s)
        for c in range(cols):
            grid.setColumnStretch(c, 1)

    def _show(self):
        on = self.chk.isChecked()
        if (on, self._folded) == self._shown:
            return   # a voice pick loads all 13 cards: only those it switched need showing
        self._shown = (on, self._folded)
        self.desc.setVisible(not self._folded)
        self.body.setVisible((on or self.hero) and not self._folded)
        self.btn_reset.setVisible(on and not self._folded)
        if bool(self.property("on")) != on:
            self.setProperty("on", on)
            self.style().unpolish(self)
            self.style().polish(self)
        self.reshaped.emit()

    def is_folded(self) -> bool:
        return self._folded

    def set_folded(self, folded: bool, asked: bool = False):
        """Folded: just the icon, name, switch and arrow. `asked`: the arrow (or the
        switch) did it, so it's remembered."""
        if folded == self._folded:
            return
        self._folded = folded
        self._paint_arrow()
        self._show()
        if asked:
            self.folded_changed.emit(folded)

    def _paint_arrow(self):
        icons.set_icon(self.arrow, "fold" if self._folded else "fold_open", "muted", "text",
                       size=12)
        name = voicefx.shown(self.cls.name)
        self.arrow.setAccessibleName(_("Show {effect}", effect=name) if self._folded
                                     else _("Fold {effect} away", effect=name))

    def _toggled(self, on):
        if on and self._folded:
            self.set_folded(False, asked=True)   # switched on: show its sliders
        self._show()
        self.changed.emit()

    def _slid(self):
        if self.hero and not self.chk.isChecked():
            self.chk.blockSignals(True)
            self.chk.setChecked(True)     # moving its slider means you want it
            self.chk.blockSignals(False)
            self._show()
        self.changed.emit()

    def mousePressEvent(self, e):
        # a click on an off card's free space turns it on (it's mostly empty then)
        if e.button() == Qt.MouseButton.LeftButton and not self.chk.isChecked() and not self.hero:
            self.chk.setChecked(True)
            return
        super().mousePressEvent(e)

    def reset(self):
        self.load({"on": self.chk.isChecked()})
        self.changed.emit()

    def state(self) -> dict:
        d = {"on": self.chk.isChecked()}
        d.update({s.q.key: s.value() for s in self.sliders})
        return d

    def load(self, cfg: dict | None):
        self.chk.blockSignals(True)
        self.chk.setChecked(bool(cfg and cfg.get("on", True)))
        self.chk.blockSignals(False)
        for s in self.sliders:
            s.set_value((cfg or {}).get(s.q.key, s.q.default))
        self._show()

    def set_error(self, msg: str):
        self.err.setText(_("⚠ Turned off after an error: {error}", error=msg) if msg else "")
        self.err.setVisible(bool(msg))

    def set_fresh(self, on: bool):
        """Highlighted: "Random voice" just set this effect."""
        if bool(self.property("fresh")) != on:
            self.setProperty("fresh", on)
            self.style().unpolish(self)
            self.style().polish(self)

    def is_fresh(self) -> bool:
        return bool(self.property("fresh"))


POWER_TEXT = {False: _("Voice changer is OFF"), True: _("Voice changer is ON")}
VOICE_ICONS = {"Walkie-talkie": "radio", "Old telephone": "speech",
               "Megaphone": "volume", "Stadium announcer": "volume",
               "Podcast voice": "mic", "Demon": "voice", "Ghost": "voice",
               "Alien": "voice", CUSTOM: "sliders"}


# the voice cards in groups, each voice in one ("All" shows them under these headings;
# a chip shows one group). Your own mix and saved voices are "Mine"; a voice not
# listed here (a new preset) lands in Funny until it's given a group.
VOICE_GROUPS = (
    ("funny", _("Funny"), ("Chipmunk", "High voice", "Hothead", "Singing monk",
                           "Underwater", "Drunk", "Choir", "Goblin", "Fairy")),
    ("scary", _("Scary"), ("Demon", "Dark lord", "Ghost", "Masked caller",
                           "Haunted radio", "Zombie", "Evil twin", "Giant")),
    ("scifi", _("Robots & sci-fi"), ("Robot", "Dalek", "Alien", "Talkbox", "Autotune",
                                     "Mecha", "Ship computer")),
    ("disguise", _("Disguise"), ("Deep voice", "Male voice", "Anonymous",
                                 "Secret detective")),
    ("places", _("Radio & places"), ("Walkie-talkie", "Old telephone", "Megaphone",
                                     "Stadium announcer", "Cave", "Podcast voice", "Pilot",
                                     "Drive-thru speaker", "Old film", "Cathedral")),
)
MINE = "mine"
FAVS = "favs"
ALL = ""
STAR = 22   # px: the favorite star in a voice card's corner


def voice_group(name: str) -> str:
    """The group a voice card goes under."""
    if name == CUSTOM or name not in voicefx.PRESETS:
        return MINE
    return next((k for k, _t, names in VOICE_GROUPS if name in names), VOICE_GROUPS[0][0])


class VoiceTile(QToolButton):
    """A voice card: picture over name. A name too long for the card ends in "…" (a
    saved voice's can be 32 characters), the whole name in its tip; an "&" in it
    shows as itself (Qt reads one as a shortcut marker)."""

    def __init__(self, title: str):
        super().__init__()
        self.title = title
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setObjectName("voicetile")
        self.setCheckable(True)
        self.setMinimumWidth(TILE_MIN_W)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(title)
        self._tip = ""          # its own tip; a cut-short name shows the whole name
        self.listed = False     # the list view: a small picture beside the name
        self._cut = False
        # a favorite? the star in its top-right corner (always shown: never on hover only)
        self.star = QToolButton(self)
        self.star.setObjectName("voicestar")
        self.star.setCheckable(True)
        self.star.setFixedSize(STAR, STAR)
        self.star.setCursor(Qt.CursorShape.PointingHandCursor)
        self.star.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.star.toggled.connect(self._show_star)
        self.toggled.connect(self._show_star)   # on the picked (accent) card: white
        self._show_star()
        self._fit_name(TILE_MIN_W)

    def _show_star(self, *_a):
        on, picked = self.star.isChecked(), self.isChecked()
        # its hover circle: the hovered card itself is btn_hover, so a lighter one there
        if self.star.property("picked") != picked:
            self.star.setProperty("picked", picked)
            self.star.style().unpolish(self.star)
            self.star.style().polish(self.star)
        icons.set_icon(self.star, "star_filled" if on else "star",
                       "on_accent" if picked else "muted",
                       "on_accent" if picked else "accent", size=16)
        tip = (_("Remove “{name}” from Favorites", name=self.title) if on
               else _("Add “{name}” to Favorites", name=self.title))
        self.star.setToolTip(tip)
        self.star.setAccessibleName(tip)

    def setToolTip(self, tip: str):
        self._tip = tip
        super().setToolTip(tip or (self.title if self._cut else ""))

    def set_listed(self, on: bool):
        self.listed = on
        self.setProperty("listed", on)
        self.setMinimumWidth(LIST_MIN_W if on else TILE_MIN_W)
        self.style().unpolish(self)
        self.style().polish(self)
        self.updateGeometry()
        self._fit_name(self.width())

    def sizeHint(self):
        s = super().sizeHint()
        return QSize(s.width(), LIST_ART + 14) if self.listed else s

    def minimumSizeHint(self):
        s = super().minimumSizeHint()
        return QSize(LIST_MIN_W, LIST_ART + 14) if self.listed else s

    def paintEvent(self, e):
        if not self.listed:
            return super().paintEvent(e)
        from PySide6.QtWidgets import QStyle, QStyleOptionToolButton, QStylePainter
        p = QStylePainter(self)
        opt = QStyleOptionToolButton()
        self.initStyleOption(opt)
        opt.text, opt.icon = "", QIcon()
        p.drawComplexControl(QStyle.ComplexControl.CC_ToolButton, opt)
        h = self.height()
        pic = self.icon().pixmap(QSize(LIST_ART, LIST_ART))
        p.drawPixmap(10, (h - LIST_ART) // 2, pic)
        p.setPen(self.palette().color(self.foregroundRole()))
        x = 10 + LIST_ART + 10
        p.drawText(QRectF(x, 0, self.width() - x - STAR - 8, h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self.text().replace("&&", "&"))

    def _fit_name(self, width: int):
        room = width - (LIST_ART + 20 + STAR + 8) if self.listed else width - 16
        shown = self.fontMetrics().elidedText(self.title, Qt.TextElideMode.ElideRight,
                                              max(0, room))
        self.setText(shown.replace("&", "&&"))
        self._cut = shown != self.title
        self.setToolTip(self._tip)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_name(self.width())
        self.star.move(self.width() - STAR - (8 if self.listed else 4),
                       (self.height() - STAR) // 2 if self.listed else 4)


class VoiceFxPanel(QWidget):
    """The voice changer: one big on/off switch, a grid of voices to pick from, a
    way to hear yourself, and (folded away) the individual effects for fine-tuning.

    `changed(spec)` with spec = {"enabled", "preset", "effects": {type: {...}}}.
    `chat_help()` asks for the Discord guide; `tip_dismissed()` means "Got it" on the
    Discord notice (the window remembers it)."""
    changed = Signal(dict)
    chat_help = Signal()
    tip_dismissed = Signal()
    folds_changed = Signal(list)   # the effect types whose cards are folded away
    hotkey_asked = Signal(str)     # right-click a voice -> Set hotkey: its name ("" key: clear)
    hotkey_cleared = Signal(str)
    renamed = Signal(str, str)     # a saved voice's old and new name
    share_asked = Signal(str)      # right-click a saved voice -> Share to the store: its name
    # an imported code holding an AI voice or a setup (storevoices.Voice, notes) -> the
    # name it was added as, "" if not (the Voice tab adds those; None: not taken here)
    take_code: Callable[[object, list], str] | None = None
    _sampled = Signal(object, str)  # Hear it's worker: (the sample or None, why not)

    COLS = 3

    def __init__(self, spec: dict, store: savedvoices.Store | None = None,
                 play_sample: Callable[[np.ndarray], object] | None = None):
        super().__init__()
        # your saved voices (Fine-tune -> "Save as a voice"): their own file, see
        # soundboard.savedvoices
        self.store = store if store is not None else savedvoices.Store()
        # the board's sounds for the Background card's "Add a sound from my board":
        # [(id, name, categories)], set by the main window
        self.sound_list: Callable[[], list[tuple[str, str, list[str]]]] = list
        self._based_on = ""   # the saved voice Fine-tune started from (Save offers it)
        # cleaned: a damaged setting (hand-edited, an old backup) mustn't stop the app
        spec = {**default_fx_spec(), **voicefx.clean_spec(spec)}
        preset = spec.get("preset")
        self._preset: str = (preset if isinstance(preset, str)
                             and (preset in voicefx.PRESETS or preset in self.store.voices)
                             else CUSTOM)
        # "My own mix" while a preset is on, so picking a preset never loses it
        effects, custom = dict(spec.get("effects", {})), dict(spec.get("custom", {}))
        self._custom: dict = custom or (effects if self._preset == CUSTOM else {})
        # Fine-tune holds your own mix, not a preset you nudged (that shows as Custom
        # too, but mustn't replace the mix you made)
        self._own = self._preset == CUSTOM and self._custom == effects
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        self.title = section_label(_("Voice changer"))
        v.addWidget(self.title)

        # ---- the switch: the Voice tab puts `head` in its card's title row, right
        self.btn_power = Switch()
        self.btn_power.setChecked(spec["enabled"])
        self.btn_power.toggled.connect(self._on_power)
        self.power_label = QLabel()
        self.power_label.setObjectName("muted")
        self.head = QWidget()
        hh = QHBoxLayout(self.head)
        hh.setContentsMargins(0, 0, 0, 0)
        hh.setSpacing(8)
        hh.addWidget(self.btn_power)
        hh.addWidget(self.power_label)
        # your mic level is in the tab's status bar (ui/voicestatus.py), over every card
        # (to hear it: the mixer's "Hear what they hear", the one switch on every tab)
        v.addWidget(hint_label(_("Change your mic live for whoever you send sounds to (Discord, "
                                 "a game, OBS). Pick a voice to turn it on, then use Hear what "
                                 "they hear at the bottom to try it.")))

        # ---- the Discord catch (always shown until "Got it": popping in when a voice was
        # picked made the card jump)
        # Measured in a real call: with Discord's default Input Profile (Voice
        # Isolation) a deep voice arrived ~20% of the time; on Studio, 93% at -0.8 dB.
        self.tip = QFrame()
        tl = QHBoxLayout(self.tip)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(8)
        # Straight into my mic, Studio makes Discord skip Onion Board (your real voice
        # goes out): Custom with noise suppression off works on the mic and the cable
        tip_text = hint_label(_("⚠ Discord deletes most of a changed voice unless its noise "
                                "suppression is off: Settings → Voice & Video → <b>Input "
                                "Profile</b> <b>Custom</b>, <b>Noise Suppression</b> "
                                "<b>None</b> (not Studio: it skips Onion Board on your mic). "
                                "Game voice chats' noise suppression does the same."))
        theme.set_tone(tip_text, "warn")
        tl.addWidget(tip_text, 1)
        self.btn_tip_help = QPushButton(_("Show me how"))
        self.btn_tip_help.clicked.connect(self.chat_help)
        tl.addWidget(self.btn_tip_help)
        self.btn_tip_ok = QPushButton(_("Got it"))
        self.btn_tip_ok.clicked.connect(self._tip_ok)
        tl.addWidget(self.btn_tip_ok)
        self._tip_enabled = True
        v.addWidget(self.tip)

        # ---- which voices show: All (under group headings), your favorites, one group
        favs = spec.get("favorites")
        self._favs: list[str] = list(favs) if isinstance(favs, list) else []
        self._group = ALL
        self.cats = QWidget()
        cflow = Flow(self.cats, gap=6)
        self._cat_group = QButtonGroup(self)
        self._cat_btns: dict[str, QPushButton] = {}
        for key, text in ((ALL, _("All")), (FAVS, _("Favorites")),
                          *((k, t) for k, t, _n in VOICE_GROUPS), (MINE, _("Mine"))):
            b = QPushButton(text.replace("&", "&&"))
            b.setObjectName("voicecat")
            b.setAccessibleName(text)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if key == FAVS:
                icons.set_icon(b, "star_filled", "accent")
            b.clicked.connect(lambda __=False, k=key: (usage.used("voice-group"),
                                                     self.show_group(k)))
            self._cat_group.addButton(b)
            self._cat_btns[key] = b
            cflow.addWidget(b)
        self._cat_btns[ALL].setChecked(True)
        self._listed = False
        self.view_toggle = ViewToggle("grid", _("Voices"))
        self.view_toggle.changed.connect(self.set_view)
        chips = QHBoxLayout()
        chips.setSpacing(12)
        chips.addWidget(self.cats, 1)
        chips.addWidget(self.view_toggle, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(chips)
        self._heads: dict[str, QLabel] = {}
        for key, text in (*((k, t) for k, t, _n in VOICE_GROUPS), (MINE, _("Mine"))):
            lbl = QLabel(text)
            lbl.setObjectName("fxgroup")
            lbl.hide()
            self._heads[key] = lbl
        self.no_favs = hint_label(_("No favorites yet. Click the star in a voice's corner "
                                    "to keep it here."))
        self.no_favs.hide()

        # ---- pick a voice: picture cards, as many a row as the width holds
        grid = self._tile_grid = QGridLayout()
        grid.setSpacing(TILE_GAP)
        self._tile_cols = self.COLS
        self.tiles = QButtonGroup(self)
        self.tiles.setExclusive(True)
        self._tile: dict[str, VoiceTile] = {}
        self.keys: dict[str, str] = {}   # voice name -> its hotkey (the window fills it in)
        self._saved_tiles: list[VoiceTile] = []
        for name in list(voicefx.PRESETS) + [CUSTOM]:
            title = _("My own mix") if name == CUSTOM else voicefx.shown(name)
            pic = art.icon(art.voice_key(name)) or (art.mystery_icon() if name != CUSTOM
                                                    else None)
            b = self._make_tile(name, title, pic, VOICE_ICONS.get(name, "wave"))
            if name == CUSTOM:
                b.setToolTip(_("Your own settings: Edit voice opens them"))
        # the die: turns on one of the voices shown, at random. It isn't a voice itself,
        # so it never lights up and has no star; it goes after the last card
        self._shown: list[str] = []   # the voices the cards show now, in order
        rt = self.random_tile = VoiceTile(_("Random voice"))
        rt.setCheckable(False)
        rt.star.hide()
        rt.setIcon(art.random_icon())
        rt.setProperty("art", True)
        rt.setIconSize(QSize(TILE_ART, TILE_ART))
        rt.setCursor(Qt.CursorShape.PointingHandCursor)
        rt.setToolTip(_("Turns on one of the voices shown here, picked at random. Click "
                        "again for another."))
        rt.clicked.connect(lambda: (usage.used("voice-roll"), self.roll()))
        for c in range(self.COLS):
            grid.setColumnStretch(c, 1)
        v.addLayout(grid)
        v.addWidget(self.no_favs)
        self.undo_bar = UndoBar(_("Bring the voice back, as it was"))
        v.addWidget(self.undo_bar)

        # ---- the voice you picked, and Edit voice (hearing it: the mixer's Hear what
        # they hear, the one switch, just below). The Voice tab pins it under
        # its scrolling cards (never scrolled out of sight); alone, it ends this panel
        self.picked = QFrame()
        self.picked.setObjectName("picked")
        # the voice's picture and name, then its buttons: side by side, or, when the
        # bar is too narrow for both (_fit_picked), the buttons on a line of their own
        self.picked_box = QBoxLayout(QBoxLayout.Direction.LeftToRight, self.picked)
        self.picked_box.setContentsMargins(12, 8, 12, 8)
        self.picked_box.setSpacing(10)
        ph = QHBoxLayout()
        ph.setSpacing(10)
        self.picked_box.addLayout(ph, 1)
        pb = QHBoxLayout()
        pb.setSpacing(10)
        self.picked_box.addLayout(pb, 1)   # an equal share: the buttons start mid-bar
        self._picked_pb = pb
        self.picked_pic = QLabel()
        self.picked_pic.setFixedSize(PICKED_ART, PICKED_ART)
        ph.addWidget(self.picked_pic)
        self.picked_name = QLabel()
        self.picked_name.setObjectName("pickedname")
        self.picked_name.setWordWrap(True)
        self.picked_name.setMinimumWidth(40)   # a long name gives way in a narrow window
        ph.addWidget(self.picked_name, 1)
        # everything for making your own voice opens in a window of its own (on the
        # card it made the tab scroll forever)
        self.btn_tweak = QPushButton(_("Edit voice"))
        icons.set_icon(self.btn_tweak, "sliders")
        self.btn_tweak.setToolTip(_("Pitch, Randomize, every effect, and your saved voices: "
                                    "build your own voice in a window beside the app"))
        self.btn_tweak.clicked.connect(lambda: (usage.used("voice-tweak"), self.open_tweak()))
        pb.addWidget(self.btn_tweak)
        # what's on top of the voice (rain, a crowd, an echo, your own sounds): a small
        # pop-up, before Edit voice (the full editor). It's the simple way in
        self.btn_effects = QPushButton(_("Effects"))
        icons.set_icon(self.btn_effects, "sounds")
        self.btn_effects.setToolTip(_("Rain, a crowd, an echo or sounds from your board, on "
                                      "top of any voice"))
        self.btn_effects.clicked.connect(lambda: (usage.used("voice-effects"),
                                                  self.open_effects()))
        pb.insertWidget(0, self.btn_effects)
        # a short line said in this voice, in your headphones (play_sample, from the
        # Voice tab: without it there's nowhere to play it, and no button)
        self.play_sample = play_sample
        self._hearing = False
        self._sampled.connect(self._sample_done)
        self.btn_sample = hear_button()
        self.btn_sample.clicked.connect(lambda: self.hear(self._preset))
        self.btn_sample.hide()
        pb.addWidget(self.btn_sample)
        pb.addStretch(1)
        v.addWidget(self.picked)
        self.picked.installEventFilter(self)   # (after its buttons: _fit_picked reads them)

        # ---- the "Edit voice" window: not modal, so the voices stay clickable
        self.dlg = QDialog(self)
        self.dlg.setWindowTitle(_("Edit voice"))
        self.dlg.setModal(False)
        self.dlg.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.dlg.finished.connect(self._tweak_closed)
        self.dlg.installEventFilter(self)
        self.destroyed.connect(self.dlg.deleteLater)   # (it may belong to the window)
        size = spec.get("panel_size")
        self._dlg_size = QSize(*size) if size else None
        dv = QVBoxLayout(self.dlg)
        dv.setContentsMargins(0, 0, 0, 10)
        dv.setSpacing(8)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page = QFrame()
        page.setObjectName("card")   # painted like the tab's cards (sliders see-through)
        pv = QVBoxLayout(page)
        pv.setContentsMargins(16, 14, 16, 12)
        pv.setSpacing(10)
        self._scroll.setWidget(page)
        dv.addWidget(self._scroll, 1)

        self.tweak = QFrame()
        self.tweak.setObjectName("tweak")
        tv = QVBoxLayout(self.tweak)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(10)
        # the window's buttons, all along the top (they wrap when it's narrow); the
        # title bar already says "Edit voice"
        tools = QWidget()
        srow = Flow(tools, gap=6)
        tv.addWidget(tools)
        self.btn_random = QPushButton(_("Randomize"))
        self.btn_random.setIcon(art.random_icon())
        self.btn_random.setIconSize(QSize(16, 16))
        self.btn_random.setToolTip(_("A random silly mix of effects, as “My own mix”: what "
                                     "it changed lights up below. Click again for another."))
        self.btn_random.clicked.connect(lambda: (usage.used("voice-random"), self.randomize()))
        srow.addWidget(self.btn_random)
        self.btn_save = QPushButton(_("Save as a voice"))
        icons.set_icon(self.btn_save, "plus")
        self.btn_save.setToolTip(_("Keep these settings as a voice with a name: it gets its "
                                   "own button under “Pick a voice”."))
        self.btn_save.clicked.connect(self.save_voice)
        srow.addWidget(self.btn_save)
        # saved voices: share one as a line of text, add one a friend sent
        self.btn_share = QPushButton(_("Copy share code"))
        icons.set_icon(self.btn_share, "copy")
        self.btn_share.setToolTip(_("Copy the saved voice that's on as a short code to paste "
                                    "to a friend: just its name and settings"))
        self.btn_share.clicked.connect(lambda: self.copy_code(self._preset))
        srow.addWidget(self.btn_share)
        self.btn_import = QPushButton(_("Import a code"))
        icons.set_icon(self.btn_import, "plus")
        self.btn_import.setToolTip(_("Add a voice someone sent you as a code (it starts "
                                     "with “OB”)"))
        self.btn_import.clicked.connect(lambda: self.import_code())
        srow.addWidget(self.btn_import)
        self.btn_bin = QPushButton(_("Recently deleted"))
        icons.set_icon(self.btn_bin, "trash")
        self.btn_bin.setToolTip(ngettext(
            "Saved voices you deleted, kept for {n} day so you can bring them back",
            "Saved voices you deleted, kept for {n} days so you can bring them back",
            savedvoices.KEEP_DAYS))
        self.btn_bin.clicked.connect(self.show_deleted)
        srow.addWidget(self.btn_bin)
        self.delay = QLabel()
        self.delay.setObjectName("pill")
        steady_number(self.delay, _("{ms} ms delay", ms="000"))
        self.delay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        srow.addWidget(self.delay)
        self.hero_box = QVBoxLayout()
        self.hero_box.setSpacing(10)
        tv.addLayout(self.hero_box)
        pv.addWidget(self.tweak)

        # ---- every effect, as cards in groups
        self.more = QWidget()
        self.box = QVBoxLayout(self.more)
        self.box.setContentsMargins(0, 6, 0, 0)
        self.box.setSpacing(8)
        self.box.addWidget(QLabel(_("<b>All effects</b>")))
        self.box.addWidget(hint_label(_("Switch effects on and drag their sliders to build "
                                        "your own voice. Changing anything switches to “My "
                                        "own mix”; like it? Save it as a voice and it gets a "
                                        "button of its own.")))
        # two columns that stack their cards tightly, each card going under the shorter
        # one: a grid (or a row per group) left holes beside the shorter cards. The
        # group titles show in one column only, where they can't leave a hole.
        self._groups: dict[str, QLabel] = {}
        for title, _types in (*GROUPS, (ADDON_GROUP, ())):
            lbl = QLabel(title)
            lbl.setObjectName("fxgroup")
            self._groups[title] = lbl
        self._fx_row = QHBoxLayout()
        self._fx_row.setSpacing(10)
        self._fx_columns: list[QVBoxLayout] = []
        for __ in range(2):
            col = QVBoxLayout()
            col.setSpacing(10)
            col.addStretch(1)
            self._fx_row.addLayout(col, 1)
            self._fx_columns.append(col)
        self.box.addLayout(self._fx_row)
        self._fx_cols = 2
        self._placed: list | None = None   # what each column holds now
        self._replace = QTimer(self)       # a voice pick changes many cards: once after
        self._replace.setSingleShot(True)
        self._replace.setInterval(0)
        self._replace.timeout.connect(self._place_cards)
        self._folded_fx: set[str] = set()
        pv.addWidget(self.more)
        pv.addStretch(1)
        done = QHBoxLayout()
        done.setContentsMargins(16, 0, 16, 0)
        done.addStretch(1)
        btn_done = QPushButton(_("Done"))
        btn_done.setObjectName("primary")
        btn_done.clicked.connect(self.dlg.close)
        done.addWidget(btn_done)
        dv.addLayout(done)

        self.rows: dict[str, EffectRow] = {}
        self._spec_effects = dict(spec.get("effects", {}))
        # the Effects pop-up's extras that are on: {type: settings}
        self._extras: dict[str, dict] = {
            t: dict(c) for t, c in self._spec_effects.items()
            if isinstance(c, dict) and c.get("on") and t in voicefx.REGISTRY
            and voicefx.REGISTRY[t].extra}
        self.effects_pop = None
        self._delay_cache: dict = {}
        self._device_ms: float | None = None
        self.add_new_effects()
        self._fresh_timer = QTimer(self)
        self._fresh_timer.setSingleShot(True)
        self._fresh_timer.timeout.connect(self._clear_fresh)
        self._fill_saved()
        self._refresh()

    # ------------------------------------------------------------------ public
    @property
    def preset(self) -> str:
        return self._preset

    def pick(self, name: str):
        """Choose a voice (a preset name or CUSTOM) and turn the changer on. Your own
        mix is kept aside while a preset is on, and comes back with "My own mix"."""
        mine = self._mine()
        if mine and name != CUSTOM:
            self._custom = {t: r.state() for t, r in self.rows.items()}
        self._preset = name
        self._clear_fresh()
        fx = voicefx.PRESETS.get(name)
        saved = self.store.voices.get(name)
        self._based_on = name if saved is not None else ""
        # (Clean up my mic is yours, not the voice's: it stays as it is)
        rows = {t: r for t, r in self.rows.items() if t not in KEEP}
        if fx is not None:
            self._own = False
            for t, r in rows.items():
                r.load({"on": True, **fx[t]} if t in fx else None)
        elif saved is not None:   # stored whole, "on" and all, like Fine-tune's rows
            self._own = False
            for t, r in rows.items():
                r.load(saved.get(t))
        elif name == CUSTOM:
            if not mine and self._custom:
                for t, r in rows.items():
                    r.load(self._custom.get(t))
            self._own = True
            self.open_tweak()   # your own mix lives in Edit voice
        self.btn_power.blockSignals(True)
        self.btn_power.setChecked(True)
        self.btn_power.blockSignals(False)
        self._refresh()
        self._emit()

    def use_mix(self, effects: dict):
        """Turn the changer on with these effects as your own mix (a setup made from a
        voice that's gone since), without opening Edit voice."""
        rows = {t: r for t, r in self.rows.items() if t not in KEEP}
        for t, r in rows.items():
            r.load(effects.get(t))
        self._custom = {t: r.state() for t, r in self.rows.items()}
        self._preset = CUSTOM
        self._own = True
        self._based_on = ""
        self._clear_fresh()
        self.btn_power.blockSignals(True)
        self.btn_power.setChecked(True)
        self.btn_power.blockSignals(False)
        self._refresh()
        self._emit()

    # never ear-splitting: louder settings are capped below their slider's top
    RANDOM_CAPS = {("compressor", "boost"): 9, ("distortion", "drive"): 20,
                   ("echo", "feedback"): 0.6, ("radio", "drive"): 14,
                   ("wobble", "vibrato"): 10}

    def randomize(self, rng: random.Random | None = None):
        """A random mix for the lols: the pitch moved well away from normal plus one
        or two other effects at random settings, as "My own mix"."""
        rng = rng or random.Random()
        others = [t for t in self.rows if t != "pitch" and t not in KEEP]
        chosen = set(rng.sample(others, min(len(others), rng.randint(1, 2))))
        if "pitch" in self.rows:
            chosen.add("pitch")
        for t, r in self.rows.items():
            if t in KEEP:
                continue
            if t not in chosen:
                r.load(None)
                continue
            cfg: dict[str, bool | float] = {"on": True}
            for q in r.cls.params:
                hi = min(q.hi, self.RANDOM_CAPS.get((t, q.key), q.hi))
                cfg[q.key] = rng.uniform(q.lo, hi)
            if t == "pitch":
                cfg["semitones"] = rng.choice((-1, 1)) * rng.uniform(4, 12)
                cfg["mix"] = 1.0
                cfg["tune"] = rng.choice((0.0, 0.0, 1.0))   # sometimes autotuned
            r.load(cfg)
        self._own = True
        self._custom = {t: r.state() for t, r in self.rows.items()}
        self._preset = CUSTOM
        self._based_on = ""
        self.btn_power.blockSignals(True)
        self.btn_power.setChecked(True)
        self.btn_power.blockSignals(False)
        self._refresh()
        self._emit()
        # show what it did: Edit voice opens with the effects it set lit up for a while
        self.open_tweak()
        for t, r in self.rows.items():
            r.set_fresh(t in chosen)
        self._fresh_timer.start(self.FRESH_MS)
        QTimer.singleShot(60, self._scroll_to_fresh)

    FRESH_MS = 8000

    def _clear_fresh(self):
        self._fresh_timer.stop()
        for r in self.rows.values():
            r.set_fresh(False)

    def _scroll_to_fresh(self):
        """Inside Edit voice, bring the lit-up effects into view."""
        fresh = [r for r in self.rows.values() if r.is_fresh()]
        if fresh:
            self._scroll.ensureWidgetVisible(fresh[-1], 0, 24)
            self._scroll.ensureWidgetVisible(fresh[0], 0, 24)

    # ------------------------------------------------------------------ the window
    DLG_SIZE = QSize(660, 720)

    def _backdrop_row(self):
        """The Background's card (None before it's made, or an add-on took its place)."""
        from soundboard.ui.backdroprow import BackdropRow
        row = self.rows.get("backdrop")
        return row if isinstance(row, BackdropRow) else None

    def open_effects(self):
        """The Effects pop-up, over the voice bar's button."""
        if self.effects_pop is None:
            from soundboard.ui.effectspopup import EffectsPopup
            self.effects_pop = EffectsPopup(self)
        self.effects_pop.open_for(self.btn_effects)

    def on_top_state(self) -> dict:
        """What the Effects pop-up shows: {"layers": {layer: level}, "sounds": [(id,
        name, level)], "extras": {type: its slider's value}} (only what's on)."""
        from soundboard.ui.effectspopup import EXTRAS
        from soundboard.voicefx import backdrop
        out: dict = {"layers": {}, "sounds": [], "extras": {}}
        row = self._backdrop_row()
        if row is not None and row.chk.isChecked():
            st = row.state()
            out["layers"] = {k: st.get(k, 0) for k in backdrop.LAYERS if st.get(k, 0) > 0}
            names = {sid: name for sid, name, _c in row._list()}
            out["sounds"] = [(d["id"], names.get(d["id"]) or _("Sound not found"),
                              d.get("level", 0.5)) for d in row.picked]
        for t, key in EXTRAS:
            cfg = self._extras.get(t)
            if cfg is not None and t in voicefx.REGISTRY:
                out["extras"][t] = cfg.get(key, voicefx.defaults(t).get(key, 0))
        return out

    def set_on_top(self, key: str, value: float | None):
        """Turn one thing on top of the voice on (at `value`), change it, or take it off
        (None): a Background layer ("rain"), a board sound ("sound:<id>") or an extra
        ("extra_echo")."""
        from soundboard.voicefx import backdrop
        row = self._backdrop_row()
        if key in backdrop.LAYERS or key.startswith("sound:"):
            if row is None:
                return
            if key.startswith("sound:"):
                sid = key[len("sound:"):]
                if value is None:
                    row._remove(sid)
                else:
                    row._level(sid, value)
            else:
                st = row.state()
                st[key] = 0.0 if value is None else value
                row.load(st)
            self._backdrop_on()
            return
        cls = voicefx.REGISTRY.get(key)
        if cls is None or not cls.extra:
            return
        if value is None:
            self._extras.pop(key, None)
        else:
            from soundboard.ui.effectspopup import EXTRAS
            cfg = self._extras.get(key) or {"on": True, **voicefx.defaults(key)}
            cfg[dict(EXTRAS)[key]] = value
            self._extras[key] = cfg
        self._refresh()
        self._emit()

    def _backdrop_on(self):
        """The Background is on while it has a sound to play, off once it has none."""
        from soundboard.voicefx import backdrop
        row = self._backdrop_row()
        if row is None:
            return
        st = row.state()
        st["on"] = any(st.get(k, 0) > 0 for k in backdrop.LAYERS) or bool(row.picked)
        row.load(st)
        self._edited("backdrop")

    def board_sound_menu(self):
        """The board's sounds, to add one behind your voice (None: no Background)."""
        row = self._backdrop_row()
        if row is None:
            return None
        m = row.add_menu()
        m.triggered.connect(lambda _a: self._backdrop_on())   # picked: it goes on with it
        return m

    def effects_count(self) -> int:
        st = self.on_top_state()
        return len(st["layers"]) + len(st["sounds"]) + len(st["extras"])

    def open_tweak(self):
        """Show the Edit voice window (at the size you left it), or bring it up."""
        if not self.dlg.isVisible():
            # owned by the app's window, not this panel: inside a card the theme makes
            # every widget see-through (QFrame#card QWidget), the window included
            if self.dlg.parentWidget() is not self.window():
                self.dlg.setParent(self.window(), self.dlg.windowFlags())
            size = self._dlg_size or self.DLG_SIZE
            screen = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
            self.dlg.resize(min(size.width(), screen.width()),
                            min(size.height(), screen.height()))
            self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow()

    def _tweak_closed(self, _result=0):
        self._clear_fresh()
        self._emit()   # its size goes into the settings, for next time

    def hideEvent(self, e):
        super().hideEvent(e)
        # the app went to the tray (not just another tab): Edit voice goes with it
        if self.dlg.isVisible():
            QTimer.singleShot(0, self.dlg, self._close_if_app_hidden)   # (dropped if it's gone)

    def _close_if_app_hidden(self):
        if qt_valid(self) and not self.window().isVisible():
            self.dlg.close()

    def _fit_picked(self):
        """The voice bar, by its width: the first of these that fits. Buttons beside
        the voice's name; under it (squeezed, "Edit voice  ·  4 on" lost its words);
        then Effects as its icon alone (its tooltip and screen-reader name still
        say it); then Edit voice without its count."""
        if getattr(self, "_fitting", False):
            return   # a text change below lays the bar out again
        self._fitting = True
        try:
            tw, tb, pb = self.btn_tweak, self.btn_effects, self._picked_pb

            def width(b, text: str) -> int:   # b's width showing `text` (icon alone: "")
                fm = b.fontMetrics()
                now = b.text()
                base = b.minimumSizeHint().width() - (fm.horizontalAdvance(now) + 6
                                                      if now else 0)
                return base + (fm.horizontalAdvance(text) + 6 if text else 0)

            full = getattr(self, "_tweak_text", "") or _("Edit voice")
            bd = getattr(self, "_effects_text", "") or _("Effects")
            hear = (self.btn_sample.minimumSizeHint().width() + pb.spacing()
                    if not self.btn_sample.isHidden() else 0)
            m = self.picked_box.contentsMargins()
            line = self.picked.width() - m.left() - m.right()
            beside = (line - PICKED_ART - min(self.picked_name.sizeHint().width(), 140)
                      - 2 * self.picked_box.spacing())
            row, col = QBoxLayout.Direction.LeftToRight, QBoxLayout.Direction.TopToBottom
            tries = ((row, full, bd, beside), (col, full, bd, line), (col, full, "", line),
                     (col, _("Edit voice"), "", line))
            want, t_text, b_text, _room = next(
                (t for t in tries
                 if width(tw, t[1]) + pb.spacing() + width(tb, t[2]) + hear <= t[3]),
                tries[-1])
            if self.picked_box.direction() != want:
                self.picked_box.setDirection(want)
            for b, text in ((tw, t_text), (tb, b_text)):
                if b.text() != text:
                    b.setText(text)
                    icons.text_gap(b)
        finally:
            self._fitting = False

    def eventFilter(self, obj, e):
        if obj is self.picked and e.type() == QEvent.Type.Resize:
            self._fit_picked()
        if obj is self.dlg and e.type() == QEvent.Type.Resize:
            if self.dlg.isVisible():
                self._dlg_size = QSize(e.size())
            cols = 2 if e.size().width() >= 600 else 1
            if cols != self._fx_cols:
                self._fx_cols = cols
                self._place_cards()
            else:
                self._reshape()   # wider or narrower: the cards' text wraps differently
        return super().eventFilter(obj, e)

    # ------------------------------------------------------------------ saved voices
    def _roll_pool(self, on: str | None = None) -> list[str]:
        """The voices Random voice picks from: the cards shown, without your own mix
        and without the voice that's on now (`on`; None: the one that's on)."""
        if on is None:
            on = self._preset if self.btn_power.isChecked() else ""
        return [n for n in self._shown if n != CUSTOM and n != on]

    def roll(self, rng: random.Random | None = None) -> str:
        """Random voice: turn on one of the voices shown, never the one that's on.
        Returns its name ("" when there's nothing to pick)."""
        pool = self._roll_pool()
        if not pool:
            return ""
        name = (rng or random.Random()).choice(pool)
        self.pick(name)
        return name

    def effects_of(self, name: str) -> dict:
        """A voice's effects as the chain takes them ({type: {"on", setting...}}), without
        Clean up my mic (it's yours, not the voice's). Your own mix: as it is now."""
        if name in voicefx.PRESETS:
            return {t: {"on": True, **cfg} for t, cfg in voicefx.PRESETS[name].items()}
        if name in self.store.voices:
            fx = self.store.voices[name]
        elif name == self._preset or name == CUSTOM:
            fx = {t: r.state() for t, r in self.rows.items()}
        else:
            fx = self._custom
        return {t: dict(cfg) for t, cfg in fx.items()
                if not on_top(t) and isinstance(cfg, dict) and cfg.get("on")}

    def hear(self, name: str):
        """Hear it: a short line in the voice `name`, in your headphones only. Made off
        the UI thread (the first one asks Windows' speech voice for the line)."""
        if self.play_sample is None or self._hearing:
            return
        usage.used("voice-hear")
        effects = self.effects_of(name)
        self._hearing = True
        self.btn_sample.setText(MAKING)

        def work():
            try:
                busy.emit(self._sampled, aipreview.fx_sample(effects), "")
            except aipreview.PreviewError as e:
                busy.emit(self._sampled, None, str(e))
            except Exception as e:  # noqa: BLE001 - the button must come back
                busy.emit(self._sampled, None, errors.plain(e))
        threading.Thread(target=work, name="voice-sample", daemon=True).start()

    def _sample_done(self, data, err: str):
        self._hearing = False
        self.btn_sample.setText(HEAR)
        if data is not None and self.play_sample is not None:
            self.play_sample(data)
        elif err:
            busy.toast(self._parent(), html.escape(
                _("⚠ Couldn't play a sample: {error}", error=err)), "warn")

    def _make_tile(self, name: str, title: str, pic, line_icon: str) -> VoiceTile:
        """A checkable voice card: its picture (ui/art.py), else a line icon, with the
        name under it."""
        b = VoiceTile(title)
        if self._listed:
            b.set_listed(True)
        if pic is not None:
            b.setIcon(pic)
            b.setProperty("art", True)
        else:
            b.setIcon(icons.icon(line_icon, "muted"))
        b.setIconSize(QSize(TILE_ART, TILE_ART))   # a line icon: as tall as a picture
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(lambda __=False, n=name: self.pick(n))
        if name != CUSTOM:
            b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            b.customContextMenuRequested.connect(
                lambda pos, n=name, w=b: self._tile_menu(n, w.mapToGlobal(pos)))
        b.star.setChecked(name in self._favs)
        b.star.toggled.connect(lambda on, n=name: self.set_favorite(n, on))
        self.tiles.addButton(b)
        self._tile[name] = b
        return b

    def _fill_saved(self):
        """(Re)make the saved voices' tiles, after "My own mix"."""
        for b in self._saved_tiles:
            self.tiles.removeButton(b)
            self._tile_grid.removeWidget(b)
            self._tile = {n: t for n, t in self._tile.items() if t is not b}
            b.hide()   # until it's gone it would paint over the regrown grid
            b.deleteLater()
        self._saved_tiles = []
        for name in self.store.voices:
            b = self._make_tile(name, name, art.icon(art.voice_key(CUSTOM)), "sliders")
            b.setToolTip(_("Your saved voice “{name}”. Click to turn the voice changer on "
                           "with it; right-click to rename or delete it.", name=name))
            self._saved_tiles.append(b)
        self._place_tiles()
        self.btn_bin.setVisible(bool(self.store.deleted))
        self._refresh()

    def _place_tiles(self):
        """The cards the picked chip shows: All under a heading per group, else one
        group (or your favorites, in the order you starred them) without headings."""
        g, cols = self._tile_grid, self._tile_cols
        names = list(voicefx.PRESETS) + [CUSTOM] + [n for n in self.store.voices
                                                    if n in self._tile]
        for w in (*self._tile.values(), *self._heads.values(), self.random_tile):
            g.removeWidget(w)
        rows: list[tuple[str, list[str]]]
        if self._group == ALL:
            rows = [(k, [n for n in names if voice_group(n) == k])
                    for k in (*(k for k, _t, _n in VOICE_GROUPS), MINE)]
        elif self._group == FAVS:
            rows = [("", [n for n in self._favs if n in self._tile])]
        else:
            rows = [("", [n for n in names if voice_group(n) == self._group])]
        shown: set[str] = set()
        self._shown = []
        r = last = last_n = 0
        for head, group in rows:
            if not group:
                continue
            if head:
                g.addWidget(self._heads[head], r, 0, 1, cols)
                r += 1
            for i, n in enumerate(group):
                g.addWidget(self._tile[n], r + i // cols, i % cols)
            last, last_n = r, len(group)
            r += (len(group) + cols - 1) // cols
            shown.update(group)
            self._shown += group
        # the die, right after the last card, while there are two voices to pick from
        rolls = len(self._roll_pool(on="")) >= 2
        if rolls:
            g.addWidget(self.random_tile, last + last_n // cols, last_n % cols)
        self.random_tile.setVisible(rolls)
        for k, lbl in self._heads.items():
            lbl.setVisible(self._group == ALL and any(voice_group(n) == k for n in shown))
        for n, b in self._tile.items():
            b.setVisible(n in shown)
        self.no_favs.setVisible(self._group == FAVS and not shown)
        for c in range(MAX_COLS):
            g.setColumnStretch(c, 1 if c < cols else 0)

    def set_view(self, view: str):
        """Picture cards, or a list: small pictures beside the names, more a screen."""
        self._listed = view == "list"
        self.view_toggle.set_view(view)
        for b in self._tile.values():
            b.set_listed(self._listed)
        self._tile_cols = 0   # refit for the new width a voice needs
        self._fit_width(self.width())

    def show_group(self, key: str):
        """Show one chip's voices (ALL, FAVS, MINE or a VOICE_GROUPS key)."""
        self._group = key
        self._cat_btns[key].setChecked(True)
        self._place_tiles()

    @property
    def favorites(self) -> list[str]:
        return list(self._favs)

    def set_favorite(self, name: str, on: bool):
        """Star or unstar a voice: Favorites lists them in the order you starred them."""
        if on == (name in self._favs):
            return
        if on:
            usage.used("voice-favorite")   # the name only (usage.py)
            self._favs.append(name)
        else:
            self._favs.remove(name)
        b = self._tile.get(name)
        if b is not None and b.star.isChecked() != on:
            b.star.setChecked(on)   # (toggled comes back here and finds nothing to do)
        if self._group == FAVS:
            self._place_tiles()
        self._emit()

    def _ask_name(self, title: str, text: str, keep: str = "") -> str:
        """A name for a saved voice, or "" if cancelled. Built-in voices' names are
        taken; so is another saved voice's, unless you agree to replace it (`keep` is
        the voice being renamed, whose own name is fine)."""
        builtin = self._builtin_names()
        while True:
            name, ok = QInputDialog.getText(self._parent(), title, _("Name:"),
                                            QLineEdit.EchoMode.Normal,
                                            text)
            name = savedvoices.clean_name(name) if ok else ""
            if not name:
                return ""
            if name.casefold() in builtin:
                QMessageBox.information(self._parent(), title,
                                        _("“{name}” is a built-in voice's name. "
                                          "Pick another one.", name=name))
                text = name
                continue
            other = self.store.find(name)
            if other is None or other == keep:
                return name
            if QMessageBox.question(self._parent(), title,
                                    _("You already have a voice called “{name}”. Replace it?",
                                      name=other)) == QMessageBox.StandardButton.Yes:
                return other
            text = name

    def save_voice(self):
        """Fine-tune's "Save as a voice": what's in Fine-tune now, under a name, as a
        tile of its own (picked straight away)."""
        suggestion = self._based_on or self.store.free_name(_("My voice"))
        if self.store.full() and self.store.find(suggestion) is None:
            busy.toast(self._parent(), html.escape(self._full_text()), "warn", 8000)
            return
        name = self._ask_name(_("Save as a voice"), suggestion)
        if not name:
            return
        effects = {t: r.state() for t, r in self.rows.items()}
        if self._mine():
            self._custom = effects   # "My own mix" stays what it was too
        name = self.store.put(name, effects)
        usage.used("voice-saved")   # the name only (usage.py), never the voice's
        self._preset, self._own, self._based_on = name, False, name
        self._fill_saved()
        self._emit()
        busy.flash(self.btn_save, _("✓ Saved"))

    def voice_names(self) -> set[str]:
        """The voices a hotkey can pick: the ready ones and your saved ones."""
        return {n for n in self._tile if n != CUSTOM}

    def saved_names(self) -> list[str]:
        return list(self.store.voices)

    def title_of(self, name: str) -> str:
        """What a voice's card calls it."""
        return voicefx.shown(name) if name in voicefx.PRESETS else name

    def _tile_menu(self, name: str, at):
        """A voice card's right-click menu: its hotkey, and for a saved voice rename,
        share and delete."""
        from soundboard.settings import pretty_key
        m = QMenu(self)
        if self.play_sample is not None:
            m.addAction(icons.icon("headphones"), HEAR, lambda: self.hear(name))
            m.addSeparator()
        key = self.keys.get(name, "")
        m.addAction(icons.icon("keyboard"),
                    _("Hotkey: {key}…", key=pretty_key(key)) if key else _("Set a hotkey…"),
                    lambda: self.hotkey_asked.emit(name))
        if key:
            m.addAction(icons.icon("close"), _("Clear hotkey"),
                        lambda: self.hotkey_cleared.emit(name))
        if name in self.store.voices:
            m.addSeparator()
            m.addAction(icons.icon("edit"), _("Rename"), lambda: self.rename_voice(name))
            m.addAction(icons.icon("copy"), _("Copy share code"), lambda: self.copy_code(name))
            m.addAction(icons.icon("upload"), _("Share to the store…"),
                        lambda: self.share_asked.emit(name))
            m.addAction(icons.icon("trash", "danger_text"), _("Delete"),
                        lambda: self.delete_voice(name))
        m.exec(at)

    @staticmethod
    def _full_text() -> str:
        return ngettext("You have {n} saved voice, the most there can be. Delete one "
                        "(right-click it) first.",
                        "You have {n} saved voices, the most there can be. Delete one "
                        "(right-click it) first.", savedvoices.MAX_VOICES)

    def _parent(self) -> QWidget:
        """Where a question goes: over Edit voice while it's open."""
        return self.dlg if self.dlg.isVisible() else self

    def copy_code(self, name: str) -> str:
        """A saved voice as a share code, onto the clipboard. Returns the code."""
        effects = self.store.voices.get(name)
        if effects is None:
            return ""
        code = savedvoices.share_code(name, effects)
        QGuiApplication.clipboard().setText(code)
        usage.used("voice-code-shared")
        if self.dlg.isVisible() and name == self._preset:
            busy.flash(self.btn_share, _("✓ Copied"))
        else:
            self.undo_bar.finish()
            self._note(_("Copied “{name}” as a share code", name=name))
        return code

    def _note(self, text: str):
        """A short result, as a corner card."""
        busy.toast(self._parent(), html.escape(text), "ok")

    def import_code(self, text: str | None = None) -> str:
        """Add a voice from a share code (asked for if not given) as a new saved voice,
        renamed if the name's taken, and turn it on; a code holding an AI voice or a
        setup goes to `take_code`. Returns the name it got ("" if none)."""
        title = _("Import a voice code")
        if text is None:
            text, ok = QInputDialog.getText(self._parent(), title,
                                            _("Paste the code someone sent you:"),
                                            QLineEdit.EchoMode.Normal, "")
            if not ok:   # OK on an empty box gets read_code's "There's no code there."
                return ""
        from soundboard import storevoices
        try:
            v, notes = storevoices.read_code(text)
        except savedvoices.CodeError as e:
            busy.toast(self._parent(), html.escape(str(e)), "warn")
            return ""
        if v.kind != "fx":
            return self.take_code(v, notes) if self.take_code is not None else ""
        name, effects = v.name, v.effects
        if self.store.full():
            busy.toast(self._parent(), html.escape(self._full_text()), "warn", 8000)
            return ""
        if name.casefold() in self._builtin_names():
            name = f"{name[:savedvoices.MAX_NAME - 9]} (shared)"
        name = self.store.free_name(name)
        on = [voicefx.shown(voicefx.REGISTRY[t].name) for t in effects]
        ask = (_("Add the voice “{name}”?<br><br>Effects: {effects}", name=html.escape(name),
                 effects=(html.escape(", ".join(on)) if on
                          else _("none (your normal voice)")))
               + "".join(f"<br><br>{html.escape(n)}" for n in notes))
        if QMessageBox.question(self._parent(), title, ask) != QMessageBox.StandardButton.Yes:
            return ""
        name = self.store.put(name, effects)
        usage.used("voice-code-imported")
        self._fill_saved()
        self.pick(name)
        if self.dlg.isVisible():
            busy.flash(self.btn_import, _("✓ Added"))
        else:   # nothing else would say it worked
            busy.toast(self._parent(), _("Added the voice “{name}”", name=html.escape(name)),
                       "ok")
        return name

    @staticmethod
    def _builtin_names() -> set[str]:
        # the English names (what's saved) and how they read on the tiles now
        names = (*voicefx.PRESETS, CUSTOM, "My own mix", "Random voice")
        return {n.casefold() for n in (*names, *map(voicefx.shown, voicefx.PRESETS),
                                       _("My own mix"))}

    def rename_voice(self, old: str):
        new = self._ask_name(_("Rename voice"), old, keep=old)
        if not new or new == old:
            return
        if self.store.find(new) not in (None, old):
            self.store.remove(new)   # agreed to replace it (it goes to the bin)
            if self._preset == new:
                self._preset = CUSTOM
        new = self.store.rename(old, new)
        if not new:
            return
        if self._preset == old:
            self._preset = new
        if self._based_on == old:
            self._based_on = new
        self._favs = [new if n == old else n for n in self._favs]
        self._fill_saved()
        self.renamed.emit(old, new)
        self._emit()

    def delete_voice(self, name: str):
        """Into the bin (Undo for a few seconds, "Recently deleted" for a month).
        If it was on, the voice you hear doesn't change: it shows as "My own mix"."""
        item = self.store.remove(name)
        if item is None:
            return
        was_on = self._preset == name
        if was_on:
            self._preset = CUSTOM
        if self._based_on == name:
            self._based_on = ""
        self._fill_saved()
        self._emit()
        self.undo_bar.show_for(_("Deleted the voice “{name}”", name=name),
                               lambda: self._undelete(item.id, was_on))

    def _undelete(self, item_id: str, was_on: bool = False) -> str:
        item = self.store.take(item_id)
        if item is None:
            return ""
        name = self.store.restore(item, item.index)
        # still sounding just like it (nothing touched since): it's the one that's on
        if was_on and self._preset == CUSTOM and \
                {t: r.state() for t, r in self.rows.items()} == self.store.voices[name]:
            self._preset = name
        self._fill_saved()
        self._emit()
        return name

    def show_deleted(self):
        from soundboard.ui.deleted import DeletedDialog
        self.undo_bar.finish()

        def back(item) -> bool:   # DeletedDialog has taken it out of the bin already
            self.store.restore(item, item.index)   # in its old place, as Undo does
            self._fill_saved()
            self._emit()
            return True
        DeletedDialog(savedvoices.VOICE, "voices", back, self, source=self.store).exec()
        self._fill_saved()

    def merge_saved(self, raw) -> int:
        """Add a backup's saved voices (the ones not here by name). Returns how many."""
        added = self.store.merge(raw)
        if added:
            self._fill_saved()
        return added

    def set_device_delay(self, ms: float | None):
        """Your sound devices' own delay (mic in + send device out), from the engine."""
        if ms != self._device_ms:
            self._device_ms = ms
            self._show_delay()

    def effects_delay(self) -> float:
        """Milliseconds the effects that are on add (worked out from their settings, so
        it's known before the mic has sent anything)."""
        if not self.btn_power.isChecked():
            return 0.0
        total = 0.0
        for t, r in self.rows.items():
            if not r.chk.isChecked():
                continue
            if r.cls.latency is voicefx.Effect.latency:
                continue   # never delays the voice: no throwaway effect to ask (Robot's ~1 ms)
            st = r.state()
            key = (t, tuple(sorted(st.items())))
            if key not in self._delay_cache:
                if len(self._delay_cache) > 256:
                    self._delay_cache.clear()
                try:
                    self._delay_cache[key] = max(0.0, float(r.cls(48000, st).latency()))
                except Exception:  # noqa: BLE001 - an add-on's effect: not counted
                    self._delay_cache[key] = 0.0
            total += self._delay_cache[key]
        return total * 1000

    def _show_delay(self):
        on = self.btn_power.isChecked()
        self.delay.setVisible(on)
        if not on:
            return
        fx = self.effects_delay()
        dev = self._device_ms
        total = fx + (dev or 0.0)
        self.delay.setText(_("{ms} ms delay", ms=f"{total:.0f}"))
        if dev is None:
            tip = _("How far behind your real voice the changed one is: {effects} ms from the "
                    "effects. Under about 100 ms feels normal to talk over; pitch effects "
                    "cost the most, the rest almost nothing.", effects=f"{fx:.0f}")
        else:
            tip = _("How far behind your real voice the changed one is: {effects} ms from the "
                    "effects + {devices} ms from your sound devices. Under about 100 ms feels "
                    "normal to talk over; pitch effects cost the most, the rest almost "
                    "nothing.", effects=f"{fx:.0f}", devices=f"{dev:.0f}")
        self.delay.setToolTip(tip)
        slow = total > 120
        if bool(self.delay.property("slow")) != slow:
            self.delay.setProperty("slow", slow)
            self.delay.style().unpolish(self.delay)
            self.delay.style().polish(self.delay)

    def set_tip_enabled(self, on: bool):
        """Whether the Discord notice may show (False once it's been dismissed)."""
        self._tip_enabled = on
        self._refresh()

    def add_new_effects(self):
        """Add cards for effect types registered since (modules loaded later)."""
        added = False
        for etype, cls in voicefx.REGISTRY.items():
            if etype in self.rows or cls.extra:   # (the extras live in the Effects pop-up)
                continue
            cfg = self._spec_effects.get(etype)
            if cfg is None:
                # mic clean-up starts on: it only makes changed voices sound better
                cfg = {"on": True} if etype == "cleanup" else {}
            if etype == "backdrop":
                from soundboard.ui.backdroprow import BackdropRow
                r = BackdropRow(cls, cfg, lambda: self.sound_list())
            else:
                r = EffectRow(cls, cfg, hero=etype in HERO)
            r.changed.connect(lambda t=etype: self._edited(t))
            r.set_folded(etype in self._folded_fx)
            r.folded_changed.connect(lambda f, t=etype: self._card_folded(t, f))
            r.reshaped.connect(self._reshape)
            if etype in HERO:
                self.hero_box.insertWidget(min(HERO.index(etype), self.hero_box.count()), r)
            self.rows[etype] = r
            added = True
        if added:
            self._place_cards()

    def set_folded(self, types):
        """Fold these effects' cards (the rest open): what `folds_changed` said last time."""
        self._folded_fx = {t for t in types if isinstance(t, str)}
        for t, r in self.rows.items():
            r.set_folded(t in self._folded_fx)

    def _card_folded(self, etype: str, folded: bool):
        (self._folded_fx.add if folded else self._folded_fx.discard)(etype)
        self.folds_changed.emit(sorted(self._folded_fx))

    def _ordered_cards(self) -> list[tuple[str, list[EffectRow]]]:
        """(group title, its cards) in reading order; add-on effects last."""
        grouped: set[str] = set(HERO)
        for _title, types in GROUPS:
            grouped.update(types)
        out = []
        for title in self._groups:
            types = dict(GROUPS).get(title) or [t for t in self.rows if t not in grouped]
            out.append((title, [self.rows[t] for t in types if t in self.rows]))
        return out

    @staticmethod
    def _card_height(c: QWidget, width: int) -> int:
        return c.heightForWidth(width) if c.hasHeightForWidth() else c.sizeHint().height()

    def _place_cards(self):
        """The effect cards into the columns: one column with the group titles, or two
        with each card under whichever column is shorter so far (in reading order),
        so a short card never leaves a hole beside a tall one."""
        groups = self._ordered_cards()
        if self._fx_cols == 1:
            plan = [[w for title, cards in groups if cards
                     for w in (self._groups[title], *cards)], []]
        else:
            width = max(200, (self.more.width() - self._fx_row.spacing()) // 2)
            plan, heights = [[], []], [0, 0]
            for _title, cards in groups:
                for c in cards:
                    i = 0 if heights[0] <= heights[1] else 1
                    plan[i].append(c)
                    heights[i] += self._card_height(c, width) + 10
        if plan == self._placed:
            return   # nothing moves (most on/off flips)
        self._placed = plan
        for lbl in self._groups.values():
            lbl.hide()
        for col in self._fx_columns:
            while col.count() > 1:           # all but the stretch
                take_out(col)
        for col, widgets in zip(self._fx_columns, plan):
            for w in widgets:
                col.insertWidget(col.count() - 1, w)   # above the column's stretch
                if isinstance(w, QLabel):
                    w.show()                           # a group title
        self._fx_row.setStretch(1, 1 if self._fx_cols == 2 else 0)

    def _reshape(self):
        """A card got taller or shorter (on/off, folded): balance the columns again."""
        if self._fx_cols == 2:
            self._replace.start()

    def _mine(self) -> bool:
        """Is Fine-tune showing your own mix? A nudged preset counts only while you
        haven't made one."""
        made = any(isinstance(e, dict) and e.get("on")
                   for t, e in self._custom.items() if t not in KEEP)
        return self._preset == CUSTOM and (self._own or not made)

    def spec(self) -> dict:
        effects = {t: r.state() for t, r in self.rows.items()}
        effects.update({t: dict(c) for t, c in self._extras.items()})
        return {"enabled": self.btn_power.isChecked(), "preset": self._preset,
                "effects": effects,
                "custom": effects if self._mine() else self._custom,
                **({"favorites": list(self._favs)} if self._favs else {}),
                **({"panel_size": [self._dlg_size.width(), self._dlg_size.height()]}
                   if self._dlg_size else {})}

    def show_errors(self, errors: dict[str, str]):
        for t, r in self.rows.items():
            r.set_error(errors.get(t, ""))

    # ------------------------------------------------------------------ internals
    def _on_power(self, on: bool):
        self._refresh()
        self._emit()

    def _tip_ok(self):
        self.set_tip_enabled(False)
        self.tip_dismissed.emit()

    def _count_on(self) -> int:
        # the voice's own effects: what's on top of it is Effects' count
        return sum(r.chk.isChecked() for t, r in self.rows.items()
                   if t not in HERO and not on_top(t))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # only a new width: fewer voices a row makes it taller, and refitting on that
        # can flip it back and forth (the Apps tab's cards jumped up and down that way)
        if e.size().width() != e.oldSize().width():
            self._fit_width(self.width())

    def _fit_width(self, width: int):
        """As many voice cards a row as the width holds, at least one."""
        lay = self.layout()
        assert lay is not None   # made in __init__
        m = lay.contentsMargins()
        room = width - m.left() - m.right()
        least = LIST_MIN_W if self._listed else TILE_MIN_W
        cols = max(1, min(MAX_COLS, (room + TILE_GAP) // (least + TILE_GAP)))
        if cols != self._tile_cols:
            self._tile_cols = cols
            self._place_tiles()
            lay.activate()

    def _refresh(self):
        on = self.btn_power.isChecked()
        self.power_label.setText(_("On") if on else _("Off"))
        self.btn_power.setAccessibleName(POWER_TEXT[on])
        self._show_picked()
        self.tip.setVisible(self._tip_enabled)
        # only a voice that's actually in use is highlighted
        self.tiles.setExclusive(False)
        for name, b in self._tile.items():
            b.setChecked(on and name == self._preset)
        self.tiles.setExclusive(True)
        n = self._count_on()
        self._tweak_text = (ngettext("Edit voice  ·  {n} on", "Edit voice  ·  {n} on", n)
                            if n else _("Edit voice"))
        self.btn_tweak.setText(self._tweak_text)   # (_fit_picked may shorten it)
        self.btn_tweak.setAccessibleName(self._tweak_text)
        ne = self.effects_count()
        text = ngettext("Effects  ·  {n}", "Effects  ·  {n}", ne) if ne else _("Effects")
        self.btn_effects.setAccessibleName(text)
        self._effects_text = text
        self.btn_effects.setText(text)
        self._fit_picked()   # a longer count may not fit beside the name any more
        mine = self._preset in self.store.voices
        _enable(self.btn_share, mine, _("Turn on one of your saved voices to share it "
                                        "(or right-click its button)"))
        self._show_delay()

    def show_picked_row(self, room: bool | None = None):
        """The bar under the cards shows only while the voice changer is on: after
        Stop it went on naming the voice, as if it were still changing your mic.
        `room`: whether the Voice tab has a place for it now (its own tab showing)."""
        if room is not None:
            self._picked_room = room
        self.picked.setVisible(getattr(self, "_picked_room", True)
                               and self.btn_power.isChecked())

    def _show_picked(self):
        """The bar under the cards: the voice that's on, by name."""
        self.show_picked_row()
        name = self._preset
        shown = _("My own mix") if name == CUSTOM else voicefx.shown(name)
        pm = art.pixmap(art.voice_key(name), PICKED_ART) if name != CUSTOM else None
        if pm is None:
            pm = icons.icon(VOICE_ICONS.get(name, "wave"), "muted").pixmap(PICKED_ART,
                                                                            PICKED_ART)
        self.picked_pic.setPixmap(pm)
        self.picked_name.setText(shown)
        self.btn_sample.setVisible(self.play_sample is not None)

    def _edited(self, etype: str = ""):
        if etype in KEEP:     # your mic clean-up, the Background: the voice stays picked
            self._refresh()
            self._emit()
            return
        self._preset = CUSTOM
        if not self.btn_power.isChecked() and any(r.chk.isChecked() for r in self.rows.values()):
            self.btn_power.blockSignals(True)
            self.btn_power.setChecked(True)   # touching an effect means you want it on
            self.btn_power.blockSignals(False)
        self._refresh()
        self._emit()

    def _emit(self):
        self.changed.emit(self.spec())
