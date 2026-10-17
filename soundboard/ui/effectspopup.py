"""The voice bar's Effects pop-up: what's on top of your voice, one slider and a ✕ each,
and buttons that add more. Rain, wind, a crowd (the Background's sounds), sounds from
your board, and the extra Robot, Radio, Echo and Reverb (voicefx.builtin's Extra*
copies). All of it stays when you pick another voice; Edit voice is the full editor.

The pop-up only reads and writes through the panel (`VoiceFxPanel.on_top_state` and
`set_on_top`), so the Background card in Edit voice and the pop-up always agree."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from soundboard import voicefx
from soundboard.i18n import _
from soundboard.ui import fit, icons
from soundboard.ui.backdroprow import _row_slider
from soundboard.ui.panel import Flow, hint_label
from soundboard.voicefx import Param, backdrop

if TYPE_CHECKING:
    from soundboard.ui.voicefxpanel import VoiceFxPanel

# the extras and the setting their one slider moves (Radio has no mix: how hard it drives)
EXTRAS = (("extra_robot", "mix"), ("extra_radio", "drive"), ("extra_echo", "mix"),
          ("extra_reverb", "mix"))
START = 0.5   # a background sound's level when you add it


def layer_param(key: str) -> Param:
    cls = voicefx.REGISTRY["backdrop"]
    return next(q for q in cls.params if q.key == key)


def extra_param(etype: str) -> Param:
    key = dict(EXTRAS)[etype]
    cls = voicefx.REGISTRY[etype]
    return next(q for q in cls.params if q.key == key)


def item_name(key: str) -> str:
    """A layer ("rain") or an extra ("extra_echo"), as the pop-up names it."""
    if key in backdrop.LAYERS:
        return voicefx.shown(layer_param(key).label)
    return voicefx.shown(voicefx.REGISTRY[key].name)


class EffectsPopup(QDialog):
    """Over the voice bar, above its Effects button. Built again on every add or ✕;
    a slider only changes its own value (the rows stay put while you drag)."""

    def __init__(self, panel: VoiceFxPanel):
        super().__init__(panel.window(), Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        fit.watch(self)
        self.panel = panel
        self.setProperty("popover", True)
        self.setObjectName("transport")
        self.setAccessibleName(_("Effects"))
        self._under: QWidget | None = None
        v = self._v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(8)
        title = QLabel(_("Effects"))
        title.setObjectName("section")
        title.setProperty("head", True)
        v.addWidget(title)
        self.hint = hint_label(_("On top of any voice: they stay when you pick another one."))
        self.hint.setWordWrap(True)
        v.addWidget(self.hint)
        self.body = QWidget()
        self.body.setObjectName("effectsbody")
        v.addWidget(self.body)
        self.btn_advanced = QPushButton(_("Advanced: Edit voice"))
        self.btn_advanced.setProperty("quiet", True)
        icons.set_icon(self.btn_advanced, "sliders", size=14)
        self.btn_advanced.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_advanced.clicked.connect(self._advanced)
        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 0)
        row.addWidget(self.btn_advanced)
        row.addStretch(1)
        v.addLayout(row)
        self.setFixedWidth(440)
        self.sliders: dict[str, QWidget] = {}
        self.removes: dict[str, QPushButton] = {}
        self.adds: dict[str, QPushButton] = {}

    # ------------------------------------------------------------- building
    def rebuild(self):
        old = self.body
        self.body = QWidget(self)
        self.body.setObjectName("effectsbody")
        self._v.replaceWidget(old, self.body)
        old.hide()
        old.deleteLater()
        self.sliders, self.removes, self.adds = {}, {}, {}
        box = QVBoxLayout(self.body)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        st = self.panel.on_top_state()
        on = [(k, st["layers"][k]) for k in backdrop.LAYERS if st["layers"].get(k, 0) > 0]
        on += [(t, st["extras"][t]) for t, _k in EXTRAS if t in st["extras"]]
        names = {k: item_name(k) for k, _l in on}
        sounds = st["sounds"]
        fm = self.fontMetrics()
        name_w = max([fm.horizontalAdvance(n) for n in names.values()]
                     + [fm.horizontalAdvance(n) for _i, n, _l in sounds] + [60])
        name_w = min(name_w + 8, 150)
        for key, level in on:
            q = layer_param(key) if key in backdrop.LAYERS else extra_param(key)
            q = Param(q.key, names[key], q.lo, q.hi, q.default, q.unit, q.step)
            s = _row_slider(q, level, name_w)
            s.changed.connect(lambda sl=s, k=key: self.panel.set_on_top(k, sl.value()))
            box.addLayout(self._with_remove(s, key, names[key]))
        for sid, name, level in sounds:
            short = fm.elidedText(name, Qt.TextElideMode.ElideRight, name_w - 4)
            s = _row_slider(Param("level", short, 0, 1, START), level, name_w)
            s.setToolTip(name)
            key = "sound:" + sid
            s.changed.connect(lambda sl=s, k=key: self.panel.set_on_top(k, sl.value()))
            box.addLayout(self._with_remove(s, key, name))
        self.hint.setVisible(not on and not sounds)
        add = hint_label(_("Add an effect"))
        add.setObjectName("fxparam")
        box.addSpacing(4)
        box.addWidget(add)
        chips = QWidget()
        chips.setObjectName("effectchips")
        flow = Flow(chips, gap=6)
        shown = {k for k, _l in on}
        for key in (*backdrop.LAYERS, *(t for t, _k in EXTRAS)):
            if key in shown or key not in backdrop.LAYERS and key not in voicefx.REGISTRY:
                continue
            flow.addWidget(self._add_button(key, item_name(key)))
        if len(sounds) < backdrop.MAX_SOUNDS:
            flow.addWidget(self._add_button("sound", _("A sound from my board")))
        box.addWidget(chips)
        # a Flow's height follows its width only once laid out: fix it for this width
        inner = self.width() - self._v.contentsMargins().left() - self._v.contentsMargins().right()
        chips.setMinimumHeight(flow.heightForWidth(inner))
        # its new height now: a widget added to a shown window stays hidden (and
        # unmeasured) until shown, and placed with the old height it hung below the bar
        self.body.show()
        self._v.activate()
        self.resize(self.width(), self.sizeHint().height())

    def _with_remove(self, s: QWidget, key: str, name: str) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setSpacing(8)
        h.addWidget(s, 1)
        x = QPushButton()
        x.setProperty("quiet", True)
        tip = _("Take “{effect}” off", effect=name)
        x.setToolTip(tip)
        x.setAccessibleName(tip)
        icons.close_button(x, 24)
        x.clicked.connect(lambda _on=False, k=key: self._remove(k))
        h.addWidget(x)
        self.sliders[key] = s
        self.removes[key] = x
        return h

    def _add_button(self, key: str, text: str) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("voicecat")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        icons.set_icon(b, "plus", size=14)
        b.setAccessibleName(_("Add {effect}", effect=text))
        b.clicked.connect(lambda _on=False, k=key, w=b: self._add(k, w))
        self.adds[key] = b
        return b

    # ------------------------------------------------------------- actions
    def _add(self, key: str, button: QPushButton):
        if key == "sound":
            m = self.panel.board_sound_menu()
            if m is None:
                return
            m.exec(button.mapToGlobal(QPoint(0, button.height())))
            m.deleteLater()
        else:
            self.panel.set_on_top(key, START if key in backdrop.LAYERS
                                  else extra_param(key).default)
        self._again()

    def _remove(self, key: str):
        self.panel.set_on_top(key, None)
        self._again()

    def _again(self):
        """Built again, still just above the button (it grows upwards)."""
        self.rebuild()
        if self._under is not None:
            self._place(self._under)

    def _advanced(self):
        self.close()
        self.panel.open_tweak()

    def open_for(self, under: QWidget):
        """Above `under` (the bar sits at the bottom of the window); below it when
        there's no room above."""
        self._under = under
        self.rebuild()
        self._place(under)
        self.show()

    def _place(self, under: QWidget):
        top = under.mapToGlobal(QPoint(0, 0))
        screen = (QApplication.screenAt(top) or under.screen()).availableGeometry()
        h = self.sizeHint().height()
        x = min(max(screen.left(), top.x()), screen.right() - self.width() + 1)
        y = top.y() - h - 6
        if y < screen.top():
            y = min(top.y() + under.height() + 6, screen.bottom() - h + 1)
        self.setGeometry(x, max(screen.top(), y), self.width(), h)
