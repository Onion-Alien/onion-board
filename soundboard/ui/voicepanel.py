"""The Voice panel: voice changer, text-to-speech, live voice-to-speech, add-ons.

`VoiceFxPanel` and `SpeechPanel` follow panel.py's pattern: they own their widgets
and emit plain dicts (`changed`) that the main window stores in the config.
`VoicePanel` lays them out as the Voice tab (cards + the tab's bottom bar).
"""
from __future__ import annotations

import functools
import html
import random
import re
import threading
import time

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QMessageBox,
                               QDialogButtonBox, QFormLayout, QFrame, QGridLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu,
                               QPlainTextEdit, QPushButton, QScrollArea, QSlider,
                               QVBoxLayout, QWidget)

from soundboard import applog
from soundboard import modules as mods
from soundboard import voicefx
from soundboard import library, net, netlog, savedvoices, theme
from soundboard.speech import customvoices, translation, winvoices
from soundboard.speech.aivoice import AiVoiceController
from soundboard.speech.live import SpeechController, clean_settings
from soundboard.ui import appstate, art, busy, icons
from soundboard.ui.panel import (UndoBar, VolumeControl, bar, card, hint_label, icon_label,
                                 section_label, vsep)
from soundboard.ui.responsive import FitWidth
from soundboard.ui.widgets import Meter
from soundboard.wheelguard import no_wheel
from soundboard import errors

CUSTOM = "Custom"
TILE_ART = 30     # px: a voice tile's picture (when there is one, see ui/art.py)
TILE_MAX_W = 210  # px: a voice tile at its widest
LIVE_MODULE = "live-voice"
IDLE_HINT = "Press Start, then just talk."
MODELS = [("Fast (base.en)", "base.en"), ("Fastest (tiny.en)", "tiny.en"),
          ("Accurate (small.en)", "small.en"), ("Any language (base)", "base"),
          ("Any language, accurate (small)", "small")]


def default_fx_spec() -> dict:
    return {"enabled": False, "preset": CUSTOM, "effects": {}}


def default_speech_settings() -> dict:
    return {"voice": "", "rate": 0, "gain": 1.0, "model": "base.en", "language": "en",
            "mute_real_voice": True, "voice_fx": True, "translate": ""}


def translations(module_list: list[mods.ModuleInfo]) -> list[mods.ModuleInfo]:
    """The languages the live voice can speak in (translation add-ons), A to Z."""
    return sorted((m for m in module_list if m.kind == "translation" and not m.error),
                  key=lambda m: m.language_name or m.language)


# =========================================================================== voice changer

class Switch(QCheckBox):
    """An on/off switch (a pill with a knob) that behaves like a checkbox."""

    def __init__(self, tip: str = ""):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tip)
        self.setFixedSize(38, 22)

    def sizeHint(self):
        return QSize(38, 22)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        r = QRectF(self.rect()).adjusted(1, 3, -1, -3)
        track = QColor(theme.T["accent"] if on else theme.T["groove"])
        if not self.isEnabled():
            track.setAlpha(110)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 4
        x = r.right() - d - 2 if on else r.left() + 2
        p.setBrush(QColor(theme.T["on_accent"] if on else theme.T["text"]))
        p.drawEllipse(QRectF(x, r.top() + 2, d, d))
        if self.hasFocus():
            p.setBrush(Qt.NoBrush)
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
        if e.type() in (QEvent.FontChange, QEvent.StyleChange):
            self._hint = QSize()
            self.updateGeometry()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.drawText(self.contentsRect(), int(self.alignment()), self._text)


def _is_switch(q: voicefx.Param) -> bool:
    """A 0/1 parameter with a step of 1 is an on/off choice, shown as a switch."""
    return q.lo == 0 and q.hi == 1 and q.step == 1


class ParamSlider(QWidget):
    """One effect setting. Compact (the speed & pitch popup, a sound's effects): name,
    slider and value on one row. Otherwise (the Voice tab's effect cards): name and
    value on top, the slider, and (when the parameter names them) what its two ends
    mean underneath. A 0/1 setting is a switch instead (`slider` is then None)."""
    changed = Signal()

    def __init__(self, q: voicefx.Param, value: float, compact: bool = True):
        super().__init__()
        self.q = q
        self.steps = max(1, int(round((q.hi - q.lo) / q.step))) if q.step else 200
        self.slider: QSlider | None = None
        self.switch: Switch | None = None
        self.name = QLabel(q.label)
        self.name.setObjectName("fxparam")
        # the effect cards' value, a slider's: as wide as its widest value
        self.val = (_ValueLabel(_value_shapes(q.lo, q.hi, q.unit, self.steps))
                    if not compact and not _is_switch(q) else QLabel())
        self.val.setObjectName("fxvalue")
        self.val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if compact:
            self.setMinimumHeight(26)
            h = QHBoxLayout(self)
            h.setContentsMargins(22, 0, 0, 0)
            self.name.setObjectName("")
            self.name.setFixedWidth(78)
            self.slider = QSlider(Qt.Horizontal)
            self.slider.setRange(0, self.steps)
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
            self.switch = Switch(q.label)
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
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, self.steps)
        self.slider.setMinimumWidth(90)
        no_wheel(self.slider)
        v.addWidget(self.slider)
        if any(q.ends):
            ends = QHBoxLayout()
            for i, word in enumerate(q.ends):
                lbl = QLabel(word)
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
        self.steps = max(1, int(round((q.hi - q.lo) / q.step))) if q.step else 200
        if self.slider is not None:
            self.slider.blockSignals(True)
            self.slider.setRange(0, self.steps)
            self.slider.blockSignals(False)
        if isinstance(self.val, _ValueLabel):
            self.val.set_shapes(_value_shapes(q.lo, q.hi, q.unit, self.steps))
        self.set_value(v)

    def value(self) -> float:
        if self.switch is not None:
            return 1.0 if self.switch.isChecked() else 0.0
        return self.q.lo + (self.q.hi - self.q.lo) * self.slider.value() / self.steps

    def set_value(self, v: float):
        v = self.q.clamp(v)
        if self.switch is not None:
            self.switch.blockSignals(True)
            self.switch.setChecked(v >= 0.5)
            self.switch.blockSignals(False)
            return
        span = (self.q.hi - self.q.lo) or 1.0
        self.slider.blockSignals(True)
        self.slider.setValue(int(round((v - self.q.lo) / span * self.steps)))
        self.slider.blockSignals(False)
        self._label()

    def text(self) -> str:
        return param_text(self.q, self.value())

    def _label(self):
        self.val.setText(self.text())
        if self.slider is not None:   # a screen reader said only "slider, 40"
            self.slider.setAccessibleName(self.q.label)
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
            "reverb": "headphones"}
# the Voice tab's "Make it yours" strip (always in view) and the effect cards' groups;
# an effect from an add-on goes under Add-ons
HERO = ("pitch", "cleanup")
HERO_TITLES = {"pitch": "Pitch & voice"}
GROUPS = (("Change the voice", ("growl", "robot")),
          ("Character", ("compressor", "tone", "radio", "distortion", "shout", "helmet")),
          ("Room", ("chorus", "echo", "reverb")))
ADDON_GROUP = "Add-ons"
# your own setting, not part of a voice: picking or saving a voice leaves it as it is
KEEP = frozenset({"cleanup"})


class EffectRow(QFrame):
    """One effect as a card: icon, name, an on/off switch, what it does, and its
    settings while it's on. `hero` (Pitch, Clean up my mic): the settings always
    show, and moving one switches the effect on."""
    changed = Signal()

    def __init__(self, cls: type[voicefx.Effect], cfg: dict, hero: bool = False):
        super().__init__()
        self.cls = cls
        self.hero = hero
        self.setObjectName("fxcard")
        self.setProperty("hero", hero)
        self.setAttribute(Qt.WA_StyledBackground)   # so [on] / [fresh] can paint
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(8)
        icon = QLabel()
        icons.set_label_icon(icon, FX_ICONS.get(cls.type, "sliders"), "accent_hi", size=16)
        icon.setObjectName("fxicon")
        head.addWidget(icon)
        title = QLabel(HERO_TITLES.get(cls.type, cls.name))
        title.setObjectName("fxname")
        head.addWidget(title)
        head.addStretch(1)
        self.btn_reset = QPushButton("Reset")
        self.btn_reset.setObjectName("fxreset")
        self.btn_reset.setCursor(Qt.PointingHandCursor)
        self.btn_reset.setToolTip(f"Put {cls.name}'s settings back to how they start")
        self.btn_reset.clicked.connect(self.reset)
        head.addWidget(self.btn_reset)
        self.chk = Switch(f"Turn {cls.name} on or off")
        self.chk.setChecked(bool(cfg.get("on")))
        head.addWidget(self.chk)
        v.addLayout(head)
        self.desc = hint_label(cls.description)
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
        cols = 2 if hero and len(cls.params) > 2 else 1
        for i, q in enumerate(cls.params):
            s = ParamSlider(q, cfg.get(q.key, q.default), compact=False)
            s.changed.connect(self._slid)
            grid.addWidget(s, i // cols, i % cols)
            self.sliders.append(s)
        for c in range(cols):
            grid.setColumnStretch(c, 1)
        v.addWidget(self.body)
        self.chk.toggled.connect(self._toggled)
        self._shown: bool | None = None   # the on/off the card last showed
        self._show()

    def _show(self):
        on = self.chk.isChecked()
        if on == self._shown:
            return   # a voice pick loads all 13 cards: only those it switched need showing
        self._shown = on
        self.body.setVisible(on or self.hero)
        self.btn_reset.setVisible(on)
        if bool(self.property("on")) != on:
            self.setProperty("on", on)
            self.style().unpolish(self)
            self.style().polish(self)

    def _toggled(self, _on):
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
        if e.button() == Qt.LeftButton and not self.chk.isChecked() and not self.hero:
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
        self.err.setText(f"⚠ Turned off after an error: {msg}" if msg else "")
        self.err.setVisible(bool(msg))

    def set_fresh(self, on: bool):
        """Highlighted: "Random voice" just set this effect."""
        if bool(self.property("fresh")) != on:
            self.setProperty("fresh", on)
            self.style().unpolish(self)
            self.style().polish(self)

    def is_fresh(self) -> bool:
        return bool(self.property("fresh"))


POWER_TEXT = {False: "Voice changer is OFF", True: "Voice changer is ON"}
POWER_SHORT = {False: "Voice changer is OFF", True: "ON  —  everyone hears it"}   # narrow
VOICE_ICONS = {"Walkie-talkie": "radio", "Old telephone": "speech",
               "Megaphone": "volume", "Stadium announcer": "volume",
               "Podcast voice": "mic", "Demon": "voice", "Ghost": "voice",
               "Alien": "voice", CUSTOM: "sliders"}


class VoiceFxPanel(QWidget):
    """The voice changer: one big on/off switch, a grid of voices to pick from, a
    way to hear yourself, and (folded away) the individual effects for fine-tuning.

    `changed(spec)` with spec = {"enabled", "preset", "effects": {type: {...}}}.
    `chat_help()` asks for the Discord guide; `tip_dismissed()` means "Got it" on the
    Discord notice (the window remembers it)."""
    changed = Signal(dict)
    chat_help = Signal()
    tip_dismissed = Signal()

    COLS = 3

    def __init__(self, spec: dict, store: savedvoices.Store | None = None):
        super().__init__()
        # your saved voices (Fine-tune -> "Save as a voice"): their own file, see
        # soundboard.savedvoices
        self.store = store if store is not None else savedvoices.Store()
        self._based_on = ""   # the saved voice Fine-tune started from (Save offers it)
        # cleaned: a damaged setting (hand-edited, an old backup) mustn't stop the app
        spec = {**default_fx_spec(), **voicefx.clean_spec(spec)}
        self._preset = spec.get("preset") if (spec.get("preset") in voicefx.PRESETS
                                              or spec.get("preset") in self.store.voices) \
            else CUSTOM
        # "My own mix" while a preset is on, so picking a preset never loses it
        effects, custom = dict(spec.get("effects", {})), dict(spec.get("custom", {}))
        self._custom: dict = custom or (effects if self._preset == CUSTOM else {})
        # Fine-tune holds your own mix, not a preset you nudged (that shows as Custom
        # too, but mustn't replace the mix you made)
        self._own = self._preset == CUSTOM and self._custom == effects
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        v.addWidget(section_label("VOICE CHANGER"))
        v.addWidget(hint_label("Change your mic live for whoever you send sounds to (Discord, a "
                               "game, OBS). Pick a voice to turn it on, then use Hear what "
                               "they hear at the bottom to try it."))

        # ---- the switch
        self.btn_power = QPushButton()
        self.btn_power.setObjectName("power")
        self.btn_power.setCheckable(True)
        self.btn_power.setMinimumHeight(42)
        self.btn_power.setCursor(Qt.PointingHandCursor)
        icons.set_icon(self.btn_power, "mic", checked_color="#ffffff")
        self.btn_power.setChecked(spec["enabled"])
        self.btn_power.toggled.connect(self._on_power)
        # the switch and your mic level side by side, next to the voice tiles (to hear
        # it: the mixer's "Hear what they hear", the one switch for that on every tab)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self.btn_power)
        top.addWidget(icon_label("mic", "Your mic level"))
        self.meter = Meter()
        self.meter.setMinimumWidth(60)
        self.meter.setToolTip("Your mic level: it moves when you talk")
        top.addWidget(self.meter, 1)
        v.addLayout(top)

        # ---- the Discord catch (shown with the changer on, until "Got it")
        # Measured in a real call: with Discord's default Input Profile (Voice
        # Isolation) a deep voice arrived ~20% of the time; on Studio, 93% at -0.8 dB.
        self.tip = QFrame()
        tl = QHBoxLayout(self.tip)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(8)
        tip_text = hint_label("⚠ Discord deletes most of a changed voice unless its "
                              "<b>Input Profile</b> is <b>Studio</b> (Settings → Voice & "
                              "Video). Game voice chats' noise suppression does the same.")
        theme.set_tone(tip_text, "warn")
        tl.addWidget(tip_text, 1)
        self.btn_tip_help = QPushButton("Show me how")
        self.btn_tip_help.clicked.connect(self.chat_help)
        tl.addWidget(self.btn_tip_help)
        self.btn_tip_ok = QPushButton("Got it")
        self.btn_tip_ok.clicked.connect(self._tip_ok)
        tl.addWidget(self.btn_tip_ok)
        self._tip_enabled = True
        v.addWidget(self.tip)

        # ---- pick a voice
        v.addWidget(QLabel("<b>Pick a voice</b>"))
        grid = self._tile_grid = QGridLayout()
        grid.setSpacing(10)
        self._tile_cols = self.COLS
        self._short = False   # the switch's short text (a narrow window)
        self._fit_hi = None   # the width the next roomier shape needed at the last fit
        self._fit_squeezed = False   # ...and none fitted: one voice a row regardless
        self.tiles = QButtonGroup(self)
        self.tiles.setExclusive(True)
        self._tile: dict[str, QPushButton] = {}
        self._saved_tiles: list[QPushButton] = []
        for name in list(voicefx.PRESETS) + [CUSTOM]:
            title = "My own mix" if name == CUSTOM else name
            pic = art.icon(art.voice_key(name)) or (art.mystery_icon() if name != CUSTOM
                                                    else None)
            b = self._make_tile(name, title, pic, VOICE_ICONS.get(name, "wave"))
            b.setToolTip("Your own settings from All effects below" if name == CUSTOM else
                         f"Sound like: {name}. Click to turn the voice changer on with it.")
        # the dice goes last, after your saved voices: it's not a voice but a way to
        # make one, so it isn't checkable
        self.btn_random = QPushButton("Random voice")
        self.btn_random.setObjectName("voicetile")
        self.btn_random.setIcon(art.random_icon())
        self.btn_random.setIconSize(QSize(TILE_ART, TILE_ART))
        self.btn_random.setProperty("art", True)
        self.btn_random.setMaximumWidth(TILE_MAX_W)
        self.btn_random.setCursor(Qt.PointingHandCursor)
        self.btn_random.setToolTip("A random silly mix of effects, as “My own mix”. All effects "
                                   "opens with what it changed lit up. Click again for "
                                   "another.")
        self.btn_random.clicked.connect(lambda: self.randomize())
        for c in range(self.COLS):
            grid.setColumnStretch(c, 1)
        v.addLayout(grid)
        self.undo_bar = UndoBar("Bring the voice back, as it was")
        v.addWidget(self.undo_bar)

        # ---- make it yours: the settings people reach for, always in view
        self.tweak = QFrame()
        self.tweak.setObjectName("tweak")
        tv = QVBoxLayout(self.tweak)
        tv.setContentsMargins(0, 4, 0, 0)
        tv.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(QLabel("<b>Make it yours</b>"))
        head.addStretch(1)
        self.delay = QLabel()
        self.delay.setObjectName("pill")
        head.addWidget(self.delay)
        tv.addLayout(head)
        self.hero_box = QVBoxLayout()
        self.hero_box.setSpacing(10)
        tv.addLayout(self.hero_box)
        srow = QHBoxLayout()
        srow.setSpacing(6)
        self.btn_save = QPushButton("Save as a voice…")
        icons.set_icon(self.btn_save, "plus")
        self.btn_save.setToolTip("Keep these settings as a voice with a name: it gets its own "
                                 "button under “Pick a voice”.")
        self.btn_save.clicked.connect(self.save_voice)
        srow.addWidget(self.btn_save)
        self.btn_bin = QPushButton("Recently deleted")
        icons.set_icon(self.btn_bin, "trash")
        self.btn_bin.setObjectName("small")
        self.btn_bin.setToolTip("Saved voices you deleted, kept for "
                                f"{savedvoices.KEEP_DAYS} days so you can bring them back")
        self.btn_bin.clicked.connect(self.show_deleted)
        srow.addWidget(self.btn_bin)
        srow.addStretch(1)
        tv.addLayout(srow)
        v.addWidget(self.tweak)

        # ---- every effect, as cards in groups (folded away)
        self.btn_more = QPushButton("All effects")
        self.btn_more.setObjectName("fold")
        self.btn_more.setCheckable(True)
        self.btn_more.toggled.connect(self._show_more)
        v.addWidget(self.btn_more, 0, Qt.AlignLeft)
        self.more = QWidget()
        self.box = QVBoxLayout(self.more)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(8)
        self.box.addWidget(hint_label("Switch effects on and drag their sliders to build your "
                                      "own voice. Changing anything switches to “My own "
                                      "mix”; like it? Save it as a voice and it gets a "
                                      "button above."))
        self._groups: dict[str, tuple[QLabel, QGridLayout]] = {}
        for title, _types in (*GROUPS, (ADDON_GROUP, ())):
            lbl = QLabel(title)
            lbl.setObjectName("fxgroup")
            g = QGridLayout()
            g.setHorizontalSpacing(10)
            g.setVerticalSpacing(10)
            self.box.addWidget(lbl)
            self.box.addLayout(g)
            self._groups[title] = (lbl, g)
        self._fx_cols = 2
        v.addWidget(self.more)
        self.rows: dict[str, EffectRow] = {}
        self._spec_effects = dict(spec.get("effects", {}))
        self._delay_cache: dict = {}
        self._device_ms: float | None = None
        self.add_new_effects()
        self._fresh_timer = QTimer(self)
        self._fresh_timer.setSingleShot(True)
        self._fresh_timer.timeout.connect(self._clear_fresh)
        self._show_more(False)
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
            self.btn_more.setChecked(True)   # your own mix lives in All effects
        self.btn_power.blockSignals(True)
        self.btn_power.setChecked(True)
        self.btn_power.blockSignals(False)
        self._refresh()
        self._emit()

    # never ear-splitting: louder settings are capped below their slider's top
    RANDOM_CAPS = {("compressor", "boost"): 9, ("distortion", "drive"): 20,
                   ("echo", "feedback"): 0.6, ("radio", "drive"): 14}

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
            cfg = {"on": True}
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
        # show what it did: Fine-tune opens with the effects it set lit up for a while
        self.btn_more.setChecked(True)
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
        """Inside the tab's scroll area, bring the lit-up effects into view."""
        fresh = [r for r in self.rows.values() if r.is_fresh()]
        area = self.parentWidget()
        while area is not None and not isinstance(area, QScrollArea):
            area = area.parentWidget()
        if area is None or not fresh:
            return
        area.ensureWidgetVisible(fresh[-1], 0, 24)
        area.ensureWidgetVisible(fresh[0], 0, 24)

    # ------------------------------------------------------------------ saved voices
    def _make_tile(self, name: str, title: str, pic, line_icon: str) -> QPushButton:
        """A checkable voice tile: its picture when there is one (ui/art.py), else a
        line icon."""
        b = QPushButton()
        if pic is not None:
            b.setIcon(pic)
            b.setIconSize(QSize(TILE_ART, TILE_ART))
            b.setProperty("art", True)
        else:
            icons.set_icon(b, line_icon, size=18)
        b.setObjectName("voicetile")
        b.setCheckable(True)
        b.setMaximumWidth(TILE_MAX_W)
        # a saved voice's name (up to 32 characters) was cut mid-word at the tile's
        # edge, and an "&" in it vanished (Qt reads it as a shortcut marker)
        room = TILE_MAX_W - b.iconSize().width() - 40
        shown = b.fontMetrics().elidedText(title, Qt.ElideRight, room)
        b.setText(shown.replace("&", "&&"))
        b.setAccessibleName(title)
        if shown != title:
            b.setToolTip(title)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(lambda _=False, n=name: self.pick(n))
        self.tiles.addButton(b)
        self._tile[name] = b
        return b

    def _fill_saved(self):
        """(Re)make the saved voices' tiles, between "My own mix" and the dice."""
        for b in self._saved_tiles:
            self.tiles.removeButton(b)
            self._tile_grid.removeWidget(b)
            self._tile = {n: t for n, t in self._tile.items() if t is not b}
            b.deleteLater()
        self._saved_tiles = []
        for name in self.store.voices:
            b = self._make_tile(name, name, art.icon(art.voice_key(CUSTOM)), "sliders")
            b.setToolTip(f"Your saved voice “{name}”. Click to turn the voice changer on "
                         "with it; right-click to rename or delete it.")
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(
                lambda pos, n=name, w=b: self._saved_menu(n, w.mapToGlobal(pos)))
            self._saved_tiles.append(b)
        self._place_tiles()
        self.btn_bin.setVisible(bool(self.store.deleted))
        self._refresh()

    def _place_tiles(self):
        g, cols = self._tile_grid, self._tile_cols
        order = [self._tile[n] for n in list(voicefx.PRESETS) + [CUSTOM]] \
            + self._saved_tiles + [self.btn_random]
        for b in order:
            g.removeWidget(b)
        for i, b in enumerate(order):
            g.addWidget(b, i // cols, i % cols)
        for c in range(self.COLS):
            g.setColumnStretch(c, 1 if c < cols else 0)

    def _ask_name(self, title: str, text: str, keep: str = "") -> str:
        """A name for a saved voice, or "" if cancelled. Built-in voices' names are
        taken; so is another saved voice's, unless you agree to replace it (`keep` is
        the voice being renamed, whose own name is fine)."""
        builtin = {n.casefold() for n in (*voicefx.PRESETS, CUSTOM, "My own mix",
                                          "Random voice")}
        while True:
            name, ok = QInputDialog.getText(self, title, "Name:", QLineEdit.Normal, text)
            name = savedvoices.clean_name(name) if ok else ""
            if not name:
                return ""
            if name.casefold() in builtin:
                QMessageBox.information(self, title, f"“{name}” is a built-in voice's name. "
                                        "Pick another one.")
                text = name
                continue
            other = self.store.find(name)
            if other is None or other == keep:
                return name
            if QMessageBox.question(self, title, f"You already have a voice called "
                                    f"“{other}”. Replace it?") == QMessageBox.Yes:
                return other
            text = name

    def save_voice(self):
        """Fine-tune's "Save as a voice": what's in Fine-tune now, under a name, as a
        tile of its own (picked straight away)."""
        suggestion = self._based_on or self.store.free_name("My voice")
        if self.store.full() and self.store.find(suggestion) is None:
            QMessageBox.information(self, "Save as a voice",
                                    f"You have {savedvoices.MAX_VOICES} saved voices, the "
                                    "most there can be. Delete one (right-click it) first.")
            return
        name = self._ask_name("Save as a voice", suggestion)
        if not name:
            return
        effects = {t: r.state() for t, r in self.rows.items()}
        if self._mine():
            self._custom = effects   # "My own mix" stays what it was too
        name = self.store.put(name, effects)
        self._preset, self._own, self._based_on = name, False, name
        self._fill_saved()
        self._emit()
        busy.flash(self.btn_save, "✓ Saved")

    def _saved_menu(self, name: str, at):
        m = QMenu(self)
        m.addAction(icons.icon("edit"), "Rename…", lambda: self.rename_voice(name))
        m.addAction(icons.icon("trash", "danger_text"), "Delete",
                    lambda: self.delete_voice(name))
        m.exec(at)

    def rename_voice(self, old: str):
        new = self._ask_name("Rename voice", old, keep=old)
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
        self._fill_saved()
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
        self.undo_bar.show_for(f"Deleted the voice “{name}”",
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
            self.store.restore(item)
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
        self.delay.setText(f"{total:.0f} ms delay")
        parts = [f"{fx:.0f} ms from the effects"]
        if dev is not None:
            parts.append(f"{dev:.0f} ms from your sound devices")
        self.delay.setToolTip("How far behind your real voice the changed one is: "
                              + " + ".join(parts) + ". Under about 100 ms feels normal "
                              "to talk over; pitch effects cost the most, the rest "
                              "almost nothing.")
        slow = total > 120
        if bool(self.delay.property("slow")) != slow:
            self.delay.setProperty("slow", slow)
            self.delay.style().unpolish(self.delay)
            self.delay.style().polish(self.delay)

    def set_level(self, level: float):
        self.meter.set_level(level)

    def set_tip_enabled(self, on: bool):
        """Whether the Discord notice may show (False once it's been dismissed)."""
        self._tip_enabled = on
        self._refresh()

    def add_new_effects(self):
        """Add cards for effect types registered since (modules loaded later)."""
        added = False
        for etype, cls in voicefx.REGISTRY.items():
            if etype in self.rows:
                continue
            cfg = self._spec_effects.get(etype)
            if cfg is None:
                # mic clean-up starts on: it only makes changed voices sound better
                cfg = {"on": True} if etype in KEEP else {}
            r = EffectRow(cls, cfg, hero=etype in HERO)
            r.changed.connect(lambda t=etype: self._edited(t))
            if etype in HERO:
                self.hero_box.insertWidget(min(HERO.index(etype), self.hero_box.count()), r)
            self.rows[etype] = r
            added = True
        if added:
            self._place_cards()

    def _place_cards(self):
        """The effect cards into their groups' grids, `_fx_cols` a row."""
        cols = self._fx_cols
        placed = set(HERO)
        for _title, types in GROUPS:
            placed.update(types)
        for title, (lbl, g) in self._groups.items():
            types = dict(GROUPS).get(title) or [t for t in self.rows if t not in placed]
            cards = [self.rows[t] for t in types if t in self.rows]
            for c in cards:
                g.removeWidget(c)
            for i, c in enumerate(cards):
                g.addWidget(c, i // cols, i % cols, Qt.AlignTop)
            for c in range(2):
                g.setColumnStretch(c, 1 if c < cols else 0)
            lbl.setVisible(bool(cards))

    def _mine(self) -> bool:
        """Is Fine-tune showing your own mix? A nudged preset counts only while you
        haven't made one."""
        made = any(isinstance(e, dict) and e.get("on")
                   for t, e in self._custom.items() if t not in KEEP)
        return self._preset == CUSTOM and (self._own or not made)

    def spec(self) -> dict:
        effects = {t: r.state() for t, r in self.rows.items()}
        return {"enabled": self.btn_power.isChecked(), "preset": self._preset,
                "effects": effects,
                "custom": effects if self._mine() else self._custom}

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

    def _show_more(self, on: bool):
        self.more.setVisible(on)
        icons.set_icon(self.btn_more, "fold_open" if on else "fold", "muted", "text", size=12)

    def _count_on(self) -> int:
        return sum(r.chk.isChecked() for t, r in self.rows.items() if t not in HERO)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # only a new width: fewer voices a row makes it taller, and refitting on that
        # can flip it back and forth (the Apps tab's cards jumped up and down that way)
        if e.size().width() != e.oldSize().width():
            self._fit_width(self.width())
            cols = 2 if self.width() >= 600 else 1
            if cols != self._fx_cols:
                self._fx_cols = cols
                self._place_cards()

    def _fit_width(self, width: int):
        """Narrow: the switch's shorter text, then fewer voices a row, down to one."""
        # the shape on now still fits and the roomier one didn't at this width: nothing
        # to try (each try is a layout pass, and a drag-resize sends one per pixel)
        if self._fit_hi is not None and width < self._fit_hi and (
                self._fit_squeezed or self.minimumSizeHint().width() <= width):
            return
        hi = float("inf")
        for short, cols in ((False, self.COLS), (True, self.COLS), (True, 2), (True, 1)):
            self._set_shape(short, cols)
            need = self.minimumSizeHint().width()
            if need <= width:
                self._fit_hi, self._fit_squeezed = hi, False
                return
            if cols > 1:
                hi = need
        # even one a row is too wide: it stays that way until the two-a-row one fits
        self._fit_hi, self._fit_squeezed = hi, True

    def _set_shape(self, short: bool, cols: int):
        if short != self._short:
            self._short = short
            self.btn_power.setText((POWER_SHORT if short else POWER_TEXT)[
                self.btn_power.isChecked()])
        if cols != self._tile_cols:
            self._tile_cols = cols
            self._place_tiles()
        self.layout().activate()

    def _refresh(self):
        self._fit_hi = None   # the switch's text may be another length: fit afresh
        on = self.btn_power.isChecked()
        self.btn_power.setText((POWER_SHORT if self._short else POWER_TEXT)[on])
        self.tip.setVisible(on and self._tip_enabled)
        # only a voice that's actually in use is highlighted
        self.tiles.setExclusive(False)
        for name, b in self._tile.items():
            b.setChecked(on and name == self._preset)
        self.tiles.setExclusive(True)
        n = self._count_on()
        self.btn_more.setText(f"All effects  ·  {n} on" if n else "All effects")
        self._show_delay()

    def _edited(self, etype: str = ""):
        if etype in KEEP:     # your mic clean-up: the voice you picked stays picked
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


# =========================================================================== speech

class SpeechPanel(QWidget):
    """Text-to-speech box and live voice-to-speech. `changed(settings)` for the config."""
    changed = Signal(dict)
    _event = Signal(dict)          # module / TTS events, hopped onto the UI thread
    _voices = Signal(list, str)
    _install_line = Signal(str)
    _install_done = Signal(bool, str)   # ok, and what went wrong when it wasn't
    _dl_progress = Signal(int, int)
    _dl_done = Signal(str)          # "" when it worked, else what went wrong
    _voice_done = Signal(str, str)  # a Windows voice install: result, what went wrong
    downloaded = Signal()           # a translation was downloaded or removed
    live_changed = Signal(bool)     # "talk as a computer voice" started / stopped

    def __init__(self, controller: SpeechController, settings: dict,
                 module_list: list[mods.ModuleInfo]):
        super().__init__()
        self.ctl = controller
        self.s = {**default_speech_settings(), **clean_settings(settings)}
        self.module = next((m for m in module_list if m.id == LIVE_MODULE and not m.error),
                           None)
        self.langs = translations(module_list)
        self._dl_cancel = False
        self._dl_busy: mods.ModuleInfo | None = None
        self._installing = False
        controller.gain = self.s["gain"]
        controller.speaker.voice = self.s["voice"]
        controller.speaker.rate = int(self.s["rate"])
        controller.mute_real_voice = self.s["mute_real_voice"]
        controller.voice_fx = self.s["voice_fx"]
        controller.on_event = self._event.emit
        self._event.connect(self._on_event)
        self._voices.connect(self._fill_voices)
        self._install_line.connect(lambda t: self.lbl_install.setText(t[-160:]))
        self._install_done.connect(self._on_install_done)
        self._dl_progress.connect(self._on_dl_progress)
        self._dl_done.connect(self._on_dl_done)
        self._voice_done.connect(self._on_voice_installed)
        self._voice_installing: mods.ModuleInfo | None = None
        self._voice_note = ""        # how the last voice install went, until it's found
        self._voice_fp: frozenset[str] | None = None   # voice tokens when last loaded
        self._loading_since = time.monotonic()   # a voice (re)load is in flight; 0 when not
        # a voice installed any way at all (here, in Settings, by a script) is noticed
        # by its registry token appearing, and the speech engine reloads to use it
        self._voice_timer = QTimer(self)
        self._voice_timer.setInterval(3000)
        self._voice_timer.timeout.connect(self._poll_voices)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)

        # ---- live voice to speech: the main event
        v.addWidget(section_label("TALK AS A COMPUTER VOICE"))
        v.addWidget(hint_label("Pick a voice and press Start. Your speech is transcribed on "
                               "this PC, then read aloud in that voice after a short delay."))
        self.live_box = QWidget()
        lv = QVBoxLayout(self.live_box)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(12)
        # speak in another language: English in, the chosen language out
        trow = QHBoxLayout()
        self.lbl_lang = QLabel("Speak in")
        trow.addWidget(self.lbl_lang)
        self.cb_lang = QComboBox()
        self.cb_lang.setToolTip("Say it in English; the computer voice says it in this "
                                "language. Each language is a one-time download.")
        trow.addWidget(self.cb_lang, 1)
        lv.addLayout(trow)
        self.tr_box = QWidget()
        tv = QVBoxLayout(self.tr_box)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(4)
        self.lbl_tr = hint_label("")
        tv.addWidget(self.lbl_tr)
        tb = QHBoxLayout()
        self.b_dl = QPushButton("Download")
        icons.set_icon(self.b_dl, "plus")
        self.b_dl.clicked.connect(self._download)
        self.b_dl_cancel = QPushButton("Cancel")
        self.b_dl_cancel.clicked.connect(self._cancel_download)
        self.b_voice_install = QPushButton("Install the voice")
        icons.set_icon(self.b_voice_install, "plus")
        self._voice_install_tip = ("Windows asks for permission once, then downloads its "
                                   "free voice for this language. It's used as soon as "
                                   "it's in; no restart.")
        self.b_voice_install.setToolTip(self._voice_install_tip)
        net.on_change(self._refresh_translation)   # Settings > Privacy's switches
        self.b_voice_install.clicked.connect(self._install_voice)
        self.b_voices = QPushButton("Windows settings")
        self.b_voices.setObjectName("small")
        self.b_voices.setToolTip("Do it by hand: Settings \u2192 Time & language \u2192 Speech "
                                 "\u2192 Add voices. It's picked up by itself once it's in.")
        self.b_voices.clicked.connect(self._get_voice)
        self.b_voices_check = QPushButton("Reload voices")
        self.b_voices_check.setObjectName("small")
        self.b_voices_check.setToolTip("Restart the speech engine to pick up new Windows "
                                       "voices (it also does this by itself)")
        self.b_voices_check.clicked.connect(self._recheck_voices_asked)
        self._voices_asked = False   # the button was pressed: say what it found
        self._voices_again = False   # a reload was asked for while one ran
        self._voice_wait = False     # sent to Windows settings for a voice; look on return
        self.b_dl_remove = QPushButton("Delete download")
        self.b_dl_remove.setObjectName("small")
        self.b_dl_remove.clicked.connect(self._remove_download)
        for b in (self.b_dl, self.b_dl_cancel, self.b_voice_install, self.b_voices,
                  self.b_voices_check, self.b_dl_remove):
            tb.addWidget(b)
        tb.addStretch(1)
        tv.addLayout(tb)
        lv.addWidget(self.tr_box)
        v.addWidget(self.live_box)

        # ---- the voice (shared by live and typed speech): set before you press Start
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(14)
        grid.addWidget(QLabel("Voice"), 0, 0)
        self.cb_voice = QComboBox()
        self.cb_voice.addItem("Loading voices…", "")
        self.cb_voice.setEnabled(False)
        # the list shows a stand-in, not the saved voice (still loading, speech failed,
        # or that voice isn't installed now): other settings changes keep the saved one
        self._voice_standin = True
        grid.addWidget(self.cb_voice, 0, 1)
        # custom voices sit under More options: this gets you there from the list itself
        self.b_add_voices = QPushButton("Add voices…")
        icons.set_icon(self.b_add_voices, "plus")
        self.b_add_voices.setToolTip("Your own voices: a TTS server on your PC (Kokoro, "
                                     "AllTalk…) or Piper voice packs")
        self.b_add_voices.clicked.connect(self.show_custom_voices)
        grid.addWidget(self.b_add_voices, 0, 2)
        grid.addWidget(QLabel("Speed"), 1, 0)
        self.sl_rate = QSlider(Qt.Horizontal)
        self.sl_rate.setMinimumHeight(28)
        self.sl_rate.setRange(-10, 10)
        self.sl_rate.setValue(int(self.s["rate"]))
        grid.addWidget(self.sl_rate, 1, 1)
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)

        self.start_box = QWidget()   # Start and its state: shown with live_box
        lv = QVBoxLayout(self.start_box)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(12)
        self.b_live = QPushButton("Start talking as the voice")
        icons.set_icon(self.b_live, "mic", "on_accent", "on_accent")
        self.b_live.setCheckable(True)
        self.b_live.setMinimumHeight(40)
        self.b_live.setObjectName("primary")
        self.b_live.toggled.connect(self._toggle_live)
        lv.addWidget(self.b_live, 0, Qt.AlignLeft)
        self.lbl_state = QLabel(IDLE_HINT)
        self.lbl_state.setTextFormat(Qt.PlainText)   # shows the module's error text
        self.lbl_state.setObjectName("muted")
        lv.addWidget(self.lbl_state)
        v.addWidget(self.start_box)
        # everything the voice was asked to say, live or typed, newest at the bottom
        lrow = QHBoxLayout()
        lrow.addWidget(section_label("WHAT THE VOICE SAID"))
        lrow.addStretch(1)
        b_clear = QPushButton("Clear")
        b_clear.setMinimumHeight(32)
        lrow.addWidget(b_clear)
        v.addLayout(lrow)
        self.said_log = QPlainTextEdit()
        self.said_log.setObjectName("speechlog")
        self.said_log.setReadOnly(True)
        self.said_log.setMaximumBlockCount(500)
        # short while empty (a tall blank box pushed More options far down), growing
        # with what's said up to a few lines, then it scrolls
        def fit_log():
            fm = self.said_log.fontMetrics()
            lines = min(5, max(2, self.said_log.document().blockCount()))
            pad = self.said_log.frameWidth() * 2 + 16
            self.said_log.setFixedHeight(lines * fm.lineSpacing() + pad)
        self.said_log.textChanged.connect(fit_log)
        fit_log()
        self.said_log.setPlaceholderText("Nothing yet. Lines show up here as they're spoken.")
        b_clear.clicked.connect(self.said_log.clear)
        v.addWidget(self.said_log)

        self.missing = QWidget()
        mv = QVBoxLayout(self.missing)
        mv.setContentsMargins(0, 8, 0, 0)
        mv.setSpacing(12)
        self.lbl_missing = hint_label("")
        mv.addWidget(self.lbl_missing)
        mrow = QHBoxLayout()
        self.b_install = QPushButton("Install speech recognition")
        icons.set_icon(self.b_install, "plus")
        self.b_install.setToolTip("One-time download, about 300 MB. Requires Python 3.12+.")
        self.b_install.clicked.connect(self._install)
        mrow.addWidget(self.b_install)
        b_open = QPushButton("Open folder")
        b_open.clicked.connect(lambda: self._open_folder(self.module, b_open))
        mrow.addWidget(b_open)
        mrow.addStretch(1)
        mv.addLayout(mrow)
        v.addWidget(self.missing)
        # install / update progress: outside `missing`, which is hidden for an update
        self.lbl_install = hint_label("")
        self.lbl_install.hide()
        v.addWidget(self.lbl_install)

        self.btn_opts = QPushButton("More options")
        self.btn_opts.setObjectName("fold")
        icons.set_icon(self.btn_opts, "fold", "muted", "text", size=12)
        self.btn_opts.setCheckable(True)
        v.addWidget(self.btn_opts, 0, Qt.AlignLeft)
        self.opts = QWidget()
        ov = QVBoxLayout(self.opts)
        ov.setContentsMargins(0, 0, 0, 0)
        grid = QGridLayout()
        grid.addWidget(QLabel("Recognition"), 2, 0)
        self.cb_model = QComboBox()
        for label, key in MODELS:
            self.cb_model.addItem(label, key)
        self.cb_model.setCurrentIndex(max(0, self.cb_model.findData(self.s["model"])))
        grid.addWidget(self.cb_model, 2, 1)
        grid.addWidget(QLabel("Language"), 3, 0)
        self.ed_lang = QLineEdit(self.s["language"])
        self.ed_lang.setPlaceholderText("en, es, de… or auto")
        self.ed_lang.setToolTip("Language you speak (two-letter code). 'auto' guesses; needs "
                                "an 'Any language' recognition model for anything but English.")
        grid.addWidget(self.ed_lang, 3, 1)
        grid.setColumnStretch(1, 1)
        ov.addLayout(grid)
        no_wheel(self.cb_voice, self.sl_rate, self.cb_model)
        self.chk_mute = QCheckBox("Mute my real mic while the computer voice is on")
        self.chk_mute.setToolTip("Others hear only the spoken voice, not your real one.")
        self.chk_mute.setChecked(self.s["mute_real_voice"])
        ov.addWidget(self.chk_mute)
        self.chk_fx = QCheckBox("Put the voice changer on the computer voice")
        self.chk_fx.setToolTip("With a voice picked under Voice changer, the computer voice "
                               "gets the same effect (a chipmunk computer voice, say).")
        self.chk_fx.setChecked(self.s["voice_fx"])
        ov.addWidget(self.chk_fx)
        self.b_update = QPushButton("Update speech recognition")
        self.b_update.setToolTip("Runs its install again: picks up what a newer Onion Board "
                                 "needs (translation, for one). Needs Python 3.12+.")
        self.b_update.clicked.connect(self._install)
        ov.addWidget(self.b_update, 0, Qt.AlignLeft)
        # ---- custom voices: a TTS server on this PC, a TTS program, Piper voice packs
        self.custom_head = section_label("CUSTOM VOICES")
        ov.addWidget(self.custom_head)
        ov.addWidget(hint_label("Use a TTS server running on your PC (Kokoro, AllTalk, any "
                                "OpenAI-style one) or drop voice packs (Piper) into the "
                                "voices folder. They join the Voice list above."))
        crow = QHBoxLayout()
        b_server = QPushButton("Add a voice server…")
        icons.set_icon(b_server, "plus")
        b_server.clicked.connect(self._add_voice_server)
        crow.addWidget(b_server)
        b_vfolder = QPushButton("Open voices folder")
        b_vfolder.setToolTip("Voice packs and voice settings go here; README.txt in it says how")
        b_vfolder.clicked.connect(lambda: busy.open_folder(customvoices.ensure_folder, b_vfolder))
        crow.addWidget(b_vfolder)
        crow.addStretch(1)
        ov.addLayout(crow)
        self.lbl_custom = hint_label("")
        self.lbl_custom.setTextFormat(Qt.PlainText)    # shows file names and errors
        self.lbl_custom.hide()
        ov.addWidget(self.lbl_custom)
        v.addWidget(self.opts)
        self.opts.hide()
        self.btn_opts.toggled.connect(lambda on: (
            self.opts.setVisible(on),
            icons.set_icon(self.btn_opts, "fold_open" if on else "fold", "muted", "text",
                           size=12)))
        self.tts_err = hint_label("")
        theme.set_tone(self.tts_err, "error")
        self.tts_err.hide()
        v.addWidget(self.tts_err)
        # ---- the tab's bottom bar (placed by VoicePanel, like every tab's bar):
        # typing a line is the extra, then the voice's volume
        self.say_bar, row = bar()
        row.addWidget(icon_label("speech", "Or type a line and it's spoken in the voice"))
        self.ed = QLineEdit()
        self.ed.setPlaceholderText("Or type a line and press Enter…")
        self.ed.returnPressed.connect(self._say)
        row.addWidget(self.ed, 1)
        b_say = QPushButton("Say")
        b_say.clicked.connect(self._say)
        b_stop = QPushButton("Stop")
        b_stop.clicked.connect(lambda: (controller.stop_speaking(),
                                        busy.flash(b_stop, "✓ Stopped", 1200)))
        row.addWidget(b_say)
        row.addWidget(b_stop)
        sep = vsep()
        row.addWidget(sep)
        vol_icon = icon_label("volume", "How loud the spoken voice is")
        row.addWidget(vol_icon)
        self.sl_gain = VolumeControl(self.s["gain"], slider_max=200, typed_max=400,
                                     tip="How loud the spoken voice is")
        row.addWidget(self.sl_gain)
        self.say_vol_group = (sep, vol_icon, self.sl_gain)
        self.say_stop = b_stop

        self.cb_voice.currentIndexChanged.connect(self._voice_picked)
        for sig in (self.sl_rate.valueChanged,
                    self.sl_gain.changed, self.cb_model.currentIndexChanged,
                    self.chk_mute.toggled, self.chk_fx.toggled):
            sig.connect(self._settings_edited)
        self.ed_lang.editingFinished.connect(self._settings_edited)
        self._fill_langs()
        self.cb_lang.currentIndexChanged.connect(self._lang_picked)
        self._refresh_module()

        app = QGuiApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._app_state)
        def warm_up():
            self._voice_fp = winvoices.fingerprint()
            voices, err = controller.tts.warm_up(), controller.tts.error
            try:
                self._voices.emit(voices, err)
            except RuntimeError:   # the panel was closed while the voices loaded
                pass
        threading.Thread(target=warm_up, name="tts-warmup", daemon=True).start()

    # ---- text to speech
    def _say(self):
        text = self.ed.text().strip()
        if text:
            self.ctl.say(text)
            self._log_said(text)
            self.ed.clear()

    def _log_said(self, text: str):
        self.said_log.appendPlainText(f"{time.strftime('%H:%M:%S')}  {text}")
        bar_ = self.said_log.verticalScrollBar()
        bar_.setValue(bar_.maximum())

    def _fill_voices(self, voices: list, error: str):
        self.cb_voice.blockSignals(True)
        self.cb_voice.clear()
        self.cb_voice.addItem("Windows default", "")
        for name in voices:
            self.cb_voice.addItem(customvoices.label(name), name)
        found = self.cb_voice.findData(self.s["voice"])
        self._voice_standin = found < 0
        self.cb_voice.setCurrentIndex(max(0, found))
        self.cb_voice.setEnabled(bool(voices))
        self.cb_voice.blockSignals(False)
        # speak in the voice the list shows: a saved voice that's been uninstalled
        # shows as "Windows default", and asking for it would fail every line
        self.ctl.speaker.voice = self.cb_voice.currentData() or ""
        self._loading_since = 0.0
        self.b_voices_check.setEnabled(True)
        self.b_voices_check.setText("Reload voices")
        if self._voices_again:   # asked for while that load ran (e.g. a server was added)
            self._voices_again = False
            QTimer.singleShot(0, self, self._recheck_voices)
        if self._voices_asked:
            self._voices_asked = False
            busy.flash(self.b_voices_check,
                       f"✓ {len(voices)} voice{'s' if len(voices) != 1 else ''}" if not error
                       else "Couldn't load them")
        m = self._lang()
        voice = self._voice_for(m) if m is not None else ""
        if m is None or voice:
            self._voice_wait = False
            self._voice_note = ""
        if self.ctl.live and m is not None and voice and self.ctl.live_voice != voice:
            # talking already: switch to the new voice now, no restart needed
            self.ctl.live_voice = voice
            short = customvoices.label(voice)
            self.lbl_state.setText(f"✓ {m.language_name} voice found: {short} speaks "
                                   "from the next line on.")
        self._refresh_translation()
        problems = getattr(self.ctl.tts, "problems", [])
        custom = getattr(self.ctl.tts, "custom", {})
        self.lbl_custom.setText("\n".join(f"⚠ {p}" for p in problems) if problems else
                                f"{len(custom)} custom voice(s) loaded." if custom else "")
        self.lbl_custom.setVisible(bool(self.lbl_custom.text()))
        if error:
            self._tts_error(f"Text-to-speech isn't available: {errors.plain(error)}")

    def show_custom_voices(self):
        """Open More options and bring its Custom voices part into view."""
        self.btn_opts.setChecked(True)
        w = self.parentWidget()
        while w is not None and not isinstance(w, QScrollArea):
            w = w.parentWidget()
        if w is not None:
            QTimer.singleShot(0, self, lambda a=w: a.ensureWidgetVisible(self.custom_head, 0, 40))

    def _add_voice_server(self):
        """A small form for a TTS server's address; saved as a .json in the voices folder."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Add a voice server")
        form = QFormLayout(dlg)
        form.addRow(hint_label("A text-to-speech server running on your PC. Most have an "
                               "OpenAI-style address ending in /v1/audio/speech; one that takes "
                               "the text in the address can use {text} in it instead."))
        ed_name = QLineEdit()
        ed_name.setPlaceholderText("Kokoro")
        ed_url = QLineEdit()
        ed_url.setPlaceholderText("http://127.0.0.1:8880/v1/audio/speech")
        ed_voice = QLineEdit()
        ed_voice.setPlaceholderText("the server's voice name, e.g. af_bella (optional)")
        ed_model = QLineEdit()
        ed_model.setPlaceholderText("optional")
        ed_key = QLineEdit()
        ed_key.setEchoMode(QLineEdit.Password)
        ed_key.setPlaceholderText("only if the server asks for one")
        for lbl, w in (("Name", ed_name), ("Address", ed_url), ("Voice", ed_voice),
                       ("Model", ed_model), ("API key", ed_key)):
            form.addRow(lbl, w)
        err = hint_label("")
        theme.set_tone(err, "error")
        err.hide()
        form.addRow(err)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        form.addRow(btns)
        btns.rejected.connect(dlg.reject)

        def ok():
            url = ed_url.text().strip()
            if not url.lower().startswith(("http://", "https://")):
                err.setText("The address starts with http:// or https://")
                err.show()
                return
            name = ed_name.text().strip() or "Voice server"
            try:
                if customvoices.server_path(name).exists() and QMessageBox.question(
                        dlg, "Add a voice server",
                        f"There's already a voice server called “{name}”. Replace it?"
                ) != QMessageBox.Yes:
                    return
                customvoices.save_server(name, url, ed_voice.text().strip(),
                                         ed_model.text().strip(), ed_key.text().strip())
            except OSError as e:
                err.setText(f"Couldn't save it in the voices folder: {errors.plain(e)}")
                err.show()
                return
            self.s["voice"] = customvoices.PREFIX + name   # pick it once it's loaded
            dlg.accept()
        btns.accepted.connect(ok)
        if dlg.exec() == QDialog.Accepted:
            self.changed.emit(dict(self.s))
            busy.toast(self, f"✓ Saved “{html.escape(ed_name.text().strip() or 'Voice server')}”"
                       " — loading its voices…", "ok")
            self._recheck_voices_asked()

    def _tts_error(self, msg: str):
        self.tts_err.setText(f"⚠ {msg}")
        self.tts_err.show()

    def _voice_picked(self, *_):
        self._voice_standin = False   # the user chose this one
        self._settings_edited()

    def _settings_edited(self, *_):
        if not self._voice_standin:
            self.s["voice"] = self.cb_voice.currentData() or ""
            self.ctl.speaker.voice = self.s["voice"]
        self.s.update(rate=self.sl_rate.value(),
                      gain=self.sl_gain.value(), model=self.cb_model.currentData(),
                      language=self.ed_lang.text().strip() or "en",
                      mute_real_voice=self.chk_mute.isChecked(),
                      voice_fx=self.chk_fx.isChecked(),
                      translate=self.cb_lang.currentData() or "")
        self.ctl.speaker.rate = self.s["rate"]
        self.ctl.gain = self.s["gain"]
        self.ctl.set_mute_real_voice(self.s["mute_real_voice"])
        self.ctl.voice_fx = self.s["voice_fx"]
        self.changed.emit(dict(self.s))

    # ---- live
    def set_modules(self, module_list: list[mods.ModuleInfo]):
        self.module = next((m for m in module_list if m.id == LIVE_MODULE and not m.error),
                           None)
        self.langs = translations(module_list)
        self._fill_langs()
        self._refresh_module()
        # "Refresh" may come right after installing a voice in Windows settings
        self._recheck_voices()

    # ---- translation
    def _lang(self) -> mods.ModuleInfo | None:
        code = self.cb_lang.currentData()
        return next((m for m in self.langs if m.language == code), None)

    def _fill_langs(self):
        self.cb_lang.blockSignals(True)
        self.cb_lang.clear()
        self.cb_lang.addItem("English (as you say it)", "")
        for m in self.langs:
            name = m.language_name or m.language
            self.cb_lang.addItem(name if m.installed
                                 else f"{name}  (download {translation.size_mb(m)} MB)",
                                 m.language)
        self.cb_lang.setIconSize(QSize(20, 20))
        self.cb_lang.setCurrentIndex(max(0, self.cb_lang.findData(self.s["translate"])))
        self.cb_lang.blockSignals(False)
        self.lbl_lang.setVisible(bool(self.langs))
        self.cb_lang.setVisible(bool(self.langs))
        self._refresh_translation()

    def _lang_picked(self, *_):
        self._settings_edited()
        self._refresh_translation()

    def _voice_for(self, m: mods.ModuleInfo) -> str:
        return self.ctl.tts.voice_for(m.language, self.s["voice"])

    def _refresh_translation(self):
        """The box under "Speak in": download it, get its Windows voice, or all set."""
        m = self._lang()
        busy = self._dl_busy is not None
        self.tr_box.setVisible(m is not None or busy)
        for b in (self.b_dl, self.b_dl_cancel, self.b_voice_install, self.b_voices,
                  self.b_voices_check, self.b_dl_remove):
            b.hide()
        self._watch_voices(False)
        if busy:
            self.b_dl_cancel.show()
            return
        if m is None:
            return
        name = m.language_name or m.language
        live = self.ctl.live
        if not m.installed:
            self.lbl_tr.setText(f"{name} needs a one-time download of its translation model "
                                f"({translation.size_mb(m)} MB). After that, translating "
                                "happens on this PC; what you say never leaves it.")
            self.b_dl.setText(f"Download {name}")
            self.b_dl.show()
            # downloading voices switched off in Settings > Privacy: greyed, saying why
            self.b_dl.setEnabled(not live and net.allowed("voices"))
            self.b_dl.setToolTip(net.off_message("voices") if not net.allowed("voices") else
                                 "Stop the computer voice to download this" if live else "")
            return
        self.b_dl_remove.setVisible(not live)
        if not self.ctl.tts.voices:        # still loading, or no speech at all
            self.lbl_tr.setText(f"Say it in English; the voice says it in {name}.")
            return
        voice = self._voice_for(m)
        if voice:
            short = customvoices.label(voice)
            self.lbl_tr.setText(f"Say it in English; {short} says it in {name}. "
                                "Translation is quick but not perfect with slang.")
        else:
            self._watch_voices(True)
            for b in (self.b_voice_install, self.b_voices, self.b_voices_check):
                b.show()
            if self._voice_installing is not None:
                self.lbl_tr.setText(f"Installing the {name} voice\u2026 Say Yes to Windows' "
                                    "permission prompt, then it downloads (a minute or two). "
                                    "It's used by itself as soon as it's in.")
                self.b_voice_install.setText("Installing\u2026")
                self.b_voice_install.setEnabled(False)
                self.b_voices.hide()
                return
            self.b_voice_install.setText(f"Install the {name} voice")
            # Windows Update can't go through the app's connection: off means not at all
            self.b_voice_install.setEnabled(net.allowed("voices"))
            self.b_voice_install.setToolTip(
                self._voice_install_tip if net.allowed("voices") else net.off_message("voices"))
            self.lbl_tr.setText(self._voice_note or (
                f"\u26a0 Windows has no {name} voice yet, so {name} can't be spoken "
                "properly. Press Install (free, one click); it's picked up by itself "
                "once it's in, even mid-sentence."))

    # ---- Windows voices
    def _install_voice(self):
        m = self._lang()
        if m is None or self._voice_installing is not None:
            return
        self._voice_installing, self._voice_note = m, ""
        self._refresh_translation()

        def work():
            try:
                busy.emit(self._voice_done, winvoices.install(m.language), "")
            except winvoices.Cancelled:
                busy.emit(self._voice_done, "cancelled", "")
            except RuntimeError as e:
                busy.emit(self._voice_done, "", errors.plain(e))
            except Exception as e:  # noqa: BLE001 - the button must come back
                applog.report(where="windows voice install")
                busy.emit(self._voice_done, "", errors.plain(e))

        threading.Thread(target=work, name="voice-install", daemon=True).start()

    def _on_voice_installed(self, result: str, err: str):
        m, self._voice_installing = self._voice_installing, None
        name = (m.language_name or m.language) if m is not None else "the"
        if err:
            self._voice_note = (f"\u26a0 Couldn't install the {name} voice: "
                                f"{errors.plain(err)}. Press "
                                "Install to try again, or add it in Windows settings.")
        elif result == "cancelled":
            self._voice_note = (f"Windows' permission prompt was closed, so the {name} "
                                "voice wasn't installed. Press Install to try again.")
        elif result == "restart":
            self._voice_note = (f"The {name} voice is installed, but Windows wants the PC "
                                "restarted to finish. After that it's picked up by itself.")
        else:
            self._voice_note = (f"The {name} voice is installed; loading it\u2026 If it "
                                "doesn't appear in a minute, press Reload voices or restart "
                                "the PC.")
        self._refresh_translation()
        if not err and result != "cancelled":
            self._recheck_voices()

    def _get_voice(self):
        self._voice_wait = busy.open_url(
            "ms-settings:speech", self.b_voices, opened="✓ Opened Windows settings",
            failed="Couldn't open Windows settings. Go to Settings → Time & language → "
                   "Speech → Add voices yourself")

    def _app_state(self, state):
        # back from Windows settings: a voice may have just been installed
        if state == Qt.ApplicationActive and self._voice_wait:
            self._recheck_voices()

    def _watch_voices(self, on: bool):
        if on and not self._voice_timer.isActive():
            self._voice_timer.start()
        elif not on:
            self._voice_timer.stop()

    def _loading(self) -> bool:
        # a load that never answered (it times out well before this) doesn't block forever
        return bool(self._loading_since) and time.monotonic() - self._loading_since < 90

    def _poll_voices(self):
        """Reload the speech engine when Windows' voice list changed since it loaded."""
        if not self._loading() and winvoices.fingerprint() != self._voice_fp:
            self._recheck_voices()

    def _recheck_voices_asked(self):
        self._voices_asked = not self._loading()
        self._recheck_voices()

    def _recheck_voices(self):
        """Look for Windows voices again, off the UI thread. Safe while talking: a line
        being spoken waits a second for the engine to come back."""
        if self._loading():
            self._voices_again = True   # run once more when this load is done
            return
        self._loading_since = time.monotonic()
        self.b_voices_check.setEnabled(False)
        self.b_voices_check.setText("Reloading\u2026")

        def work():
            self._voice_fp = winvoices.fingerprint()
            voices = self.ctl.tts.refresh()
            try:
                self._voices.emit(voices, self.ctl.tts.error)
            except RuntimeError:   # the panel was closed meanwhile
                pass
        threading.Thread(target=work, name="tts-refresh", daemon=True).start()

    def _download(self):
        m = self._lang()
        if m is None or self._dl_busy is not None:
            return
        self._dl_busy, self._dl_cancel = m, False
        _enable(self.cb_lang, False, "Waiting for the download to finish")
        _enable(self.b_live, False, "Waiting for the download to finish")
        self._refresh_translation()
        self.lbl_tr.setText(f"Downloading {m.language_name}\u2026 0%")
        netlog.cause("voices", f"You downloaded the {m.language_name} translation model")

        def work():
            try:
                translation.download(m, lambda *a: busy.emit(self._dl_progress, *a),
                                     lambda: self._dl_cancel)
                busy.emit(self._dl_done, "")
            except translation.Cancelled:
                busy.emit(self._dl_done, "cancelled")
            except RuntimeError as e:
                busy.emit(self._dl_done, errors.plain(e))
            except Exception as e:  # noqa: BLE001 - the UI must never stay on "Downloading…"
                applog.report(where="translation download")
                busy.emit(self._dl_done, errors.plain(e))

        threading.Thread(target=work, name="translation-download", daemon=True).start()

    def _cancel_download(self):
        self._dl_cancel = True
        self.b_dl_cancel.setEnabled(False)
        if self._dl_busy is not None:
            self.lbl_tr.setText("Cancelling…")

    def _on_dl_progress(self, done: int, total: int):
        m = self._dl_busy
        if m is not None and not self._dl_cancel:
            pct = f"{done * 100 // total}%" if total else f"{done // 1_000_000} MB"
            self.lbl_tr.setText(f"Downloading {m.language_name}\u2026 {pct}")

    def _on_dl_done(self, err: str):
        m, self._dl_busy = self._dl_busy, None
        _enable(self.cb_lang, not self.ctl.live, "Stop the computer voice to change this")
        _enable(self.b_live, not self._installing, "Waiting for the install to finish")
        self.b_dl_cancel.setEnabled(True)
        self._fill_langs()
        if err and m is not None:
            self.lbl_tr.setText("Download cancelled." if err == "cancelled"
                                else f"\u26a0 {m.language_name}: {errors.plain(err)}. "
                                     "Check your internet "
                                     "connection and press Download again.")
        self.downloaded.emit()

    def _remove_download(self):
        m = self._lang()
        if m is None or self.ctl.live:
            return
        if QMessageBox.question(
                self, "Delete download",
                f"Delete the downloaded {m.language_name} translation? You can download "
                "it again any time.") != QMessageBox.Yes:
            return

        def go():
            translation.remove(m)
            self._fill_langs()
            self.downloaded.emit()
            return not translation.model_dir(m).exists()

        def said(gone: bool):
            if gone:
                busy.toast(self, f"✓ Deleted the {html.escape(m.language_name)} download", "ok")
            else:
                busy.toast(self, "Couldn't delete all of it (a file is in use). Restart Onion "
                                 "Board and try again.", "warn")
        busy.run_busy(self.b_dl_remove, "Deleting…", go, said)

    def _refresh_module(self):
        m = self.module
        ok = m is not None and m.installed
        self.live_box.setVisible(ok)
        self.start_box.setVisible(ok)
        self.missing.setVisible(not ok)
        self.b_install.setVisible(m is not None and not ok)
        self.b_update.setVisible(m is not None)
        if m is None:
            self.lbl_missing.setText(
                "The live-voice add-on is missing from this copy of Onion Board. Run the "
                "installer again (it comes with every install), then press Refresh below.")
        elif not ok:
            self.lbl_missing.setText("Live voice needs its speech recognition installed first "
                                     "(runs on this PC; what you say never leaves it). "
                                     "Needs Python 3.12+ from python.org.")
            self.lbl_missing.setToolTip(str(m.path))

    def _install(self):
        m = self.module
        if m is None or self._installing:
            return          # one pip at a time: two into the same environment break it
        self._installing = True
        for b in (self.b_install, self.b_update, self.b_live):
            b.setEnabled(False)
        self.b_install.setText("Installing… (a few minutes)")
        self.b_update.setText("Updating… (a few minutes)")
        self.lbl_install.show()
        self.lbl_install.setText("starting…")

        def work():
            try:
                ok = mods.install(m, lambda line: busy.emit(self._install_line, line))
                busy.emit(self._install_done, ok, "")
            except Exception as e:  # noqa: BLE001 - the buttons must come back
                applog.report(where="module install")
                busy.emit(self._install_done, False, errors.plain(e))

        threading.Thread(target=work, name="module-install", daemon=True).start()

    def _on_install_done(self, ok: bool, err: str = ""):
        self._installing = False
        self.b_install.setEnabled(True)
        self.b_install.setText("Install speech recognition")
        _enable(self.b_update, not self.ctl.live, "Stop the computer voice to change this")
        self.b_update.setText("Update speech recognition")
        _enable(self.b_live, self._dl_busy is None, "Waiting for the download to finish")
        if ok:
            self.lbl_install.hide()
            self._refresh_module()
            self.lbl_state.setText("Installed. Press Start and talk.")
        else:
            self.lbl_install.setText(f"⚠ Install failed: {err or self.lbl_install.text()}. "
                                     "Press it again to retry; if it keeps failing, run "
                                     "install.bat in the add-on's folder to see why.")

    def _toggle_live(self, on: bool):
        if on and not self.ctl.live:
            # only our own models: any other name makes the helper download that repo
            model = self.s["model"] if self.s["model"] in {d for _n, d in MODELS} else MODELS[0][1]
            lang = str(self.s["language"]).strip().lower()
            lang = lang if re.fullmatch(r"auto|[a-z]{2,3}", lang) else "en"
            args = ["--model", model, "--language", lang]
            m = self._lang()
            self.ctl.live_voice = None
            if m is not None:
                if not m.installed:
                    self._set_live_ui(False, f"Download {m.language_name} first (above).")
                    return
                args += ["--translate", str(translation.model_dir(m))]
                self.ctl.live_voice = self._voice_for(m) or None
            try:
                self.ctl.start_live(self.module, args)
            except RuntimeError as e:
                self._set_live_ui(False, f"⚠ {errors.plain(e)}")
                return
            self._set_live_ui(True, "starting…")
        elif not on and self.ctl.live:
            self.ctl.stop_live()
            self._set_live_ui(False, IDLE_HINT)

    def _set_live_ui(self, on: bool, state: str):
        self.b_live.blockSignals(True)
        self.b_live.setChecked(on)
        self.b_live.blockSignals(False)
        self.b_live.setText("Stop the computer voice" if on else "Start talking as the voice")
        self.live_changed.emit(on)
        for w in (self.cb_model, self.ed_lang, self.cb_lang):
            _enable(w, not on, "Stop the computer voice to change this")
        _enable(self.b_update, not on and not self._installing,
                "Stop the computer voice to change this" if on
                else "Waiting for the install to finish")
        self.lbl_state.setText(state)
        self._refresh_translation()

    def _on_event(self, ev: dict):
        t = ev.get("type")
        text = str(ev.get("text", ""))
        if t == "tts_error":
            self._tts_error(f"Couldn't speak that line: {text}")
        elif t == "status":
            self.lbl_state.setText(text)
        elif t == "ready":
            self.lbl_state.setText("● listening")
        elif t == "vad":
            self.lbl_state.setText("● hearing you…" if ev.get("speaking") else "● listening")
        elif t == "final" and text:
            orig = str(ev.get("original", ""))
            self._log_said(f"{text}   (you said: {orig})" if orig else text)
        elif t == "error":
            self.lbl_state.setText(f"⚠ {text}")
        elif t == "stopped":
            self._set_live_ui(False, f"⚠ stopped: {text}" if text else "stopped")

    @staticmethod
    def _open_folder(module: mods.ModuleInfo | None = None, btn=None):
        """The module's own folder, or the user add-ons folder when it isn't there yet."""
        d = module.path if module is not None else library.APP_DIR / "modules"

        def make():
            d.mkdir(parents=True, exist_ok=True)
            return d
        busy.open_folder(make, btn)


# =========================================================================== add-ons list

class ModulesList(QWidget):
    """`refresh` asks for a rescan (the Voice tab does it off the UI thread); the
    button stays on "Checking…" until the next show_modules()."""
    refresh = Signal()
    shown = Signal()

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        v.addWidget(section_label("ADD-ONS"))
        self.list = QVBoxLayout()
        self.list.setSpacing(10)
        v.addLayout(self.list)
        row = QHBoxLayout()
        b = self.b_refresh = QPushButton("Refresh")
        b.clicked.connect(self._refresh)
        o = QPushButton("Open folder")
        o.clicked.connect(lambda: SpeechPanel._open_folder(btn=o))
        row.addWidget(b)
        row.addWidget(o)
        row.addStretch(1)
        v.addLayout(row)

    def _refresh(self):
        if busy.is_busy(self.b_refresh):
            return   # already checking: a double click mustn't start it twice
        busy.hold_until(self.b_refresh, "Checking…", self.shown, lambda: "✓ Up to date")
        self.refresh.emit()

    def show_modules(self, infos: list[mods.ModuleInfo]):
        while self.list.count():
            w = self.list.takeAt(0).widget()
            if w:
                w.deleteLater()
        e = html.escape   # error text is often "<class ...>"-shaped

        def row(text: str, tip: str):
            lbl = hint_label(text)
            lbl.setTextFormat(Qt.RichText)
            lbl.setToolTip(tip)
            self.list.addWidget(lbl)
        # the Voice tab's own add-ons only: Onion Watch lives on the Triggers tab (and
        # Settings → Add-ons), and the languages share one line
        voice = [m for m in infos if m.kind not in ("triggers", "remote")]
        langs = [m for m in voice if m.kind == "translation" and not m.error]
        for m in voice:
            if m in langs:
                continue
            if m.error:
                state = f"⚠ {m.error}"
            elif m.kind == "service" and not m.installed:
                state = ("not set up yet: press Install speech recognition above"
                         if m.id == LIVE_MODULE else "not set up yet")
            elif m.kind == "effects":
                state = "on" if m.loaded else "not loaded"
            else:
                state = "ready"
            row(f"<b>{e(m.name)}</b> {e(m.version)} · {e(state)}",
                f"{m.description}" + chr(10) + str(m.path))
        if langs:
            have = [m.language_name or m.name for m in langs if m.installed]
            more = [m.language_name or m.name for m in langs if not m.installed]
            parts = [f"{', '.join(have)} downloaded"] if have else []
            if more:
                parts.append(f"{', '.join(more)} can be downloaded under Speak in")
            row(f"<b>Languages</b> · {e('; '.join(parts))}",
                chr(10).join(f"{m.language_name or m.name}: {translation.size_mb(m)} MB"
                          for m in langs))
        if not voice:
            self.list.addWidget(hint_label("No voice add-ons installed."))
        self.shown.emit()


class VoicePanel(QWidget):
    """The Voice tab, shaped like the others: cards (live voice first, then the
    voice changer and add-ons) and the tab's bottom bar. Owns the chain wiring for
    the engine.

    `fx_changed(spec)` and `speech_changed(settings)` are for the main window to
    save in the config."""
    fx_changed = Signal(dict)
    speech_changed = Signal(dict)
    active_changed = Signal(bool)   # the voice changer or the computer voice is on / off
    _scanned = Signal(object, object)   # the Refresh button's worker: (modules, AI voices)

    def __init__(self, engine, fx_spec: dict | None = None, speech: dict | None = None):
        super().__init__()
        self.engine = engine
        self._active = None              # last is_active() sent out (active_changed)
        self.chain = voicefx.VoiceChain()
        engine.voice_chain = self.chain
        self.modules = mods.discover()
        mods.load_effects(self.modules)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page = FitWidth()   # the voice changer fits itself to the width (_fit_width)
        cols = self._cols = QHBoxLayout(page)
        cols.setContentsMargins(4, 4, 8, 12)
        cols.setSpacing(16)
        lcol, rcol = QVBoxLayout(), QVBoxLayout()
        for col in (lcol, rcol):
            col.setSpacing(16)
            cols.addLayout(col, 1)
        scroll.setWidget(page)
        outer.addWidget(scroll, 1)

        # left: the voice changer. It always starts off (the voice you picked is kept):
        # left on from last time, it changed your mic the moment the app opened.
        self.fx = VoiceFxPanel({**voicefx.clean_spec(fx_spec), "enabled": False})
        self.fx.changed.connect(self._fx_changed)
        fx_card, fv = card(roomy=True)
        fv.addWidget(self.fx)
        lcol.addWidget(fx_card)
        lcol.addStretch(1)

        # Right: computer voice and its add-ons.
        self.controller = SpeechController(engine, self.chain, lambda ev: None)
        self.speech = SpeechPanel(self.controller, speech or {}, self.modules)
        self.speech.changed.connect(self.speech_changed)
        self.speech.changed.connect(lambda _s: self._emit_active())   # the tab's picture
        self.speech.downloaded.connect(lambda: self.addons.show_modules(self.modules))
        self.speech.live_changed.connect(lambda _on: self._emit_active())
        # AI voices first: the live voice changer; then the computer voice
        from soundboard.ui.aivoicepanel import AiVoicePanel
        self.ai_controller = AiVoiceController(self.chain, lambda ev: None)
        saved = speech.get("ai") if isinstance(speech, dict) else None   # may be damaged
        self.ai = AiVoicePanel(self.ai_controller, saved, self.modules)
        self.ai.changed.connect(self._ai_changed)
        self.ai.live_changed.connect(self._ai_live)
        self.ai.modules_changed.connect(self.rescan_modules)
        ai_card, aiv = card(roomy=True)
        aiv.addWidget(self.ai)
        rcol.addWidget(ai_card)
        self.speech.live_changed.connect(self._speech_live)
        live_card, lv = card(roomy=True)
        lv.addWidget(self.speech)
        rcol.addWidget(live_card)
        self.addons = ModulesList()
        self.addons.refresh.connect(self._rescan_in_background)
        self._scanned.connect(self._apply_scan)
        self._scanning = False
        self.addons.show_modules(self.modules)
        add_card, av = card(roomy=True)
        av.addWidget(self.addons)
        rcol.addWidget(add_card)
        rcol.addStretch(1)

        outer.addWidget(self.speech.say_bar)
        self.chain.configure(self.fx.spec())

        # the voice changer's mic meter (only while the tab is showing)
        self._meter_timer = QTimer(self)
        self._meter_timer.timeout.connect(self._meter)
        appstate.slow_in_background(self, self._meter_timer, 50)   # behind a game

    def showEvent(self, e):
        super().showEvent(e)
        self._meter_timer.start(appstate.interval(50))

    def hideEvent(self, e):
        super().hideEvent(e)
        self._meter_timer.stop()   # no wake-ups while another tab is showing

    def _meter(self):
        if self.isVisible():
            e = self.engine
            self.fx.set_level(e.level_mic if e.mic_stream is not None else 0.0)
            self._ticks = getattr(self, "_ticks", 0) + 1
            if self._ticks % 20 == 1:       # the devices' delay: once a second is plenty
                delay = getattr(e, "device_delay", None)
                s = delay() if callable(delay) else None
                self.fx.set_device_delay(None if s is None else s * 1000)

    def fit_steps(self):
        """What the main window may hide here when it gets small (ui/responsive.py)."""
        from soundboard.ui import responsive as r
        return [(40, "w", r.hide(*self.speech.say_vol_group)),
                (50, "w", r.hide(self.speech.say_stop))]

    def stack_steps(self):
        from soundboard.ui import responsive as r
        return [r.stack(self._cols)]

    def _fx_changed(self, spec: dict):
        if self.chain.errors:              # give a bypassed effect another go after an edit
            self.chain.errors.clear()      # (configure rebuilds; clear_errors() would twice)
        self.chain.configure(spec)
        self.fx.show_errors({})
        self.fx_changed.emit(spec)
        self._emit_active()

    def _ai_changed(self, s: dict):
        self.speech.s["ai"] = s            # kept with the speech settings
        self.speech_changed.emit(dict(self.speech.s))

    def _ai_live(self, on: bool):
        if on:                             # one replacement for your voice at a time
            self.speech.b_live.setChecked(False)
        self._emit_active()

    def _speech_live(self, on: bool):
        if on:
            self.ai.stop()

    def is_active(self) -> bool:
        """Something here is changing what others hear from your mic."""
        return (self.fx.btn_power.isChecked() or self.speech.b_live.isChecked()
                or self.ai.is_on())

    def _emit_active(self):
        # only when it flips: every slider step lands here, and each send redraws the tab
        on = self.is_active()
        if on != self._active:
            self._active = on
            self.active_changed.emit(on)

    def tab_icon(self) -> str:
        """A consistent line icon; the live dot indicates whether voice is active."""
        return "voice"

    def poll(self):
        """Call from the UI's status timer: surfaces effects the chain had to bypass."""
        errors = dict(self.chain.errors)   # the mic thread writes it
        if errors:
            self.fx.show_errors(errors)

    def rescan_modules(self, found: list | None = None, ai_voices: list | None = None):
        """`found` / `ai_voices`: already read from disk by _rescan_in_background."""
        self.modules = mods.discover() if found is None else found
        mods.load_effects(self.modules)
        self.fx.add_new_effects()
        self.chain.configure(self.fx.spec())
        self.speech.set_modules(self.modules)
        self.ai.set_modules(self.modules, ai_voices)
        self.addons.show_modules(self.modules)

    def _rescan_in_background(self):
        """The add-ons' Refresh button: the folder scan and voices.json read on a
        worker (17 ms of disk on a slow drive), the rest back on the UI thread."""
        if self._scanning:
            return
        self._scanning = True

        def work():
            from soundboard.speech import aivoice
            from soundboard.ui.aivoicepanel import read_voices
            found = voices = None
            try:
                found = mods.discover()
                voices = read_voices(next((m for m in found if m.id == aivoice.MODULE_ID
                                           and not m.error), None))
            except Exception:  # noqa: BLE001 - scanned again on the UI thread instead
                found = voices = None
            try:
                self._scanned.emit(found, voices)
            except RuntimeError:   # the tab was closed meanwhile
                pass
        threading.Thread(target=work, daemon=True, name="addon-scan").start()

    def _apply_scan(self, found, voices):
        self._scanning = False
        try:
            self.rescan_modules(found, voices)
        except Exception:
            self.addons.shown.emit()   # never leave Refresh stuck on "Checking…"
            raise

    def shutdown(self):
        """Closing the app, or the tab switched off in Settings > Tabs. A download or
        install still running finishes quietly (busy.emit) or, a translation, stops."""
        self._meter_timer.stop()
        self.speech._dl_cancel = True
        self.ai.shutdown()
        self.controller.shutdown()
        self.engine.voice_chain = None
