"""One effect's card in the voice changer (`EffectRow`): its switch and sliders, and
which tab of Edit voice it's on."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from soundboard.ui.kit import theme
from soundboard import voicefx
from soundboard.ui.kit import icons
from soundboard.ui.kit.panel import hint_label, reset_button
from soundboard.i18n import _
from soundboard.ui.voice.fxcontrols import ParamSlider, Switch


# the app's own line icons (ui/kit/icons.py), like everywhere else
FX_ICONS = {"pitch": "mic", "growl": "wave", "robot": "keyboard",
            "compressor": "volume", "tone": "sliders", "radio": "radio", "distortion": "live",
            "shout": "speech", "helmet": "voice", "chorus": "shuffle", "echo": "history",
            "reverb": "headphones", "polish": "star", "harmony": "music", "ringmod": "wave",
            "backdrop": "sounds",
            "flanger": "reload", "wobble": "ear"}
# the Voice tab's "Edit voice" window's tabs: Main (these), then one a group;
# an effect from an add-on goes under Add-ons (a tab only when there is one)
HERO = ("pitch",)
HERO_TITLES = {"pitch": _("Pitch & voice")}
MAIN_TAB = _("Main")
GROUPS = ((_("Change the voice"), ("harmony", "growl", "robot", "ringmod", "monk")),
          (_("Character"), ("compressor", "tone", "radio", "distortion", "shout", "helmet",
                            "polish")),
          (_("Room"), ("chorus", "flanger", "wobble", "echo", "reverb", "backdrop")))
ADDON_GROUP = _("Add-ons")
# yours, not the voice's: picking a voice leaves it as it is (the Background's
# sounds); with the Effects pop-up's extras, they're "on top"
KEEP = voicefx.KEEP


def on_top(etype: str) -> bool:
    """Not part of the voice: kept when you pick another one, never saved with it."""
    return voicefx.on_top(etype)


class EffectRow(QFrame):
    """One effect as a card: icon, name, an on/off switch, what it does, and its
    settings while it's on. `hero` (Pitch): the settings always
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
