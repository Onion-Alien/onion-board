"""The voice bar's Effects pop-up: what's on top of your voice, one slider and a ✕ each,
and buttons that add more. Rain, wind, a crowd (the Background's sounds), sounds from
your board, and the extra Robot, Radio, Echo, Reverb, Autotune and Bit crusher (Extra*
copies in voicefx.builtin). All of it stays when you pick another voice; Edit voice is
the full editor.

The pop-up only reads and writes through the panel (`VoiceFxPanel.on_top_state` and
`set_on_top`), so the Background card in Edit voice and the pop-up always agree."""
from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

import numpy as np

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from soundboard.core import usage
from soundboard import voicefx
from soundboard.i18n import _
from soundboard.ui.kit import fit, icons
from soundboard.ui.voice.backdroprow import _row_slider
from soundboard.ui.kit.panel import Flow, hint_label
from soundboard.voicefx import Param, backdrop

if TYPE_CHECKING:
    from soundboard.ui.voice.voicefxpanel import VoiceFxPanel

# the extras and the setting their one slider moves (Radio has no mix: how hard it drives)
EXTRAS = (("extra_robot", "mix"), ("extra_radio", "drive"), ("extra_echo", "mix"),
          ("extra_reverb", "mix"), ("extra_autotune", "tune"), ("extra_bitcrush", "mix"))
START = 0.5   # a background sound's level when you add it
LISTEN_S, LISTEN_GAIN = 4.0, 0.12   # its ▶: seconds of it, and how loud (it's at RMS 1)
LISTEN_SID = "effects-listen:preview"   # (":preview": the headphones only)
log = logging.getLogger(__name__)

LISTEN_DOT = 20   # the ▶ circle inside a background sound's chip


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


def place_over(pop: QWidget, under: QWidget):
    """A pop-up above `under` (the voice bar sits at the bottom of the window); below
    it when there's no room above."""
    top = under.mapToGlobal(QPoint(0, 0))
    screen = (QApplication.screenAt(top) or under.screen()).availableGeometry()
    h = pop.sizeHint().height()
    x = min(max(screen.left(), top.x()), screen.right() - pop.width() + 1)
    y = top.y() - h - 6
    if y < screen.top():
        y = min(top.y() + under.height() + 6, screen.bottom() - h + 1)
    pop.setGeometry(x, max(screen.top(), y), pop.width(), h)


class EffectsPopup(QDialog):
    """Over the voice bar, above its Effects button. Built again on every add or ✕;
    a slider only changes its own value (the rows stay put while you drag)."""

    preview_ready = Signal(int, str, object)

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
        self.listens: dict[str, QPushButton] = {}
        self._preview_gen = 0
        self.preview_ready.connect(self._preview_done)
        self._listening: str | None = None   # the background sound heard right now

    # ------------------------------------------------------------- building
    def rebuild(self):
        old = self.body
        self.body = QWidget(self)
        self.body.setObjectName("effectsbody")
        self._v.replaceWidget(old, self.body)
        old.hide()
        old.deleteLater()
        self.sliders, self.removes, self.adds, self.listens = {}, {}, {}, {}
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
        shown = {k for k, _l in on}
        backs = [k for k in backdrop.LAYERS if k not in shown]
        extras = [t for t, _k in EXTRAS if t not in shown and t in voicefx.REGISTRY]
        groups = []
        if backs or len(sounds) < backdrop.MAX_SOUNDS:
            groups.append((_("Background sounds"),
                           [self._listen_chip(k) for k in backs]
                           + ([self._add_button("sound", _("A sound from my board"))]
                              if len(sounds) < backdrop.MAX_SOUNDS else [])))
        if extras:
            groups.append((_("Add an effect"),
                           [self._add_button(t, item_name(t)) for t in extras]))
        flows = []
        for title, buttons in groups:
            head = hint_label(title)
            head.setObjectName("fxparam")
            box.addSpacing(4)
            box.addWidget(head)
            chips = QWidget()
            chips.setObjectName("effectchips")
            flow = Flow(chips, gap=6)
            for b in buttons:
                flow.addWidget(b)
            box.addWidget(chips)
            flows.append((chips, flow))
        # a Flow's height follows its width only once laid out: fix it for this width
        inner = self.width() - self._v.contentsMargins().left() - self._v.contentsMargins().right()
        for chips, flow in flows:
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

    def _listen_chip(self, key: str) -> QPushButton:
        """A background sound's add chip, with a round ▶ inside its right end: a few
        seconds of it in your own headphones first (you couldn't hear one before adding
        it). One pill, so the row doesn't read as twice as many buttons."""
        b = self._add_button(key, item_name(key))
        b.setProperty("listen", True)
        p = QPushButton(b)
        p.setObjectName("chipplay")
        p.setCursor(Qt.CursorShape.PointingHandCursor)
        tip = _("Hear {effect} (only you)", effect=item_name(key))
        p.setToolTip(tip)
        p.setAccessibleName(tip)
        p.setFixedSize(LISTEN_DOT, LISTEN_DOT)
        p.clicked.connect(lambda _on=False, k=key: self._listen(k))
        self.listens[key] = p
        self._dot_look(key)
        b.installEventFilter(self)   # keeps the dot at its right end as it's sized
        return b

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Resize and obj.property("listen"):
            for p in obj.findChildren(QPushButton, "chipplay"):
                p.move(obj.width() - p.width() - 4, (obj.height() - p.height()) // 2)
        return super().eventFilter(obj, ev)

    def _dot_look(self, key: str):
        p = self.listens.get(key)
        if p is None:
            return
        on = self._listening == key
        p.setProperty("playing", on)
        p.style().unpolish(p)
        p.style().polish(p)
        icons.set_icon(p, "stop" if on else "play", "on_accent" if on else "text_hi", size=12)

    def _listen(self, key: str):
        """Play LISTEN_S of `key` in the headphones; again (the same one): stop it."""
        engine = getattr(self.panel.window(), "engine", None)
        if engine is None:
            return
        was = self._listening
        self._preview_gen += 1
        gen = self._preview_gen
        engine.stop(LISTEN_SID)
        if was == key:
            self._listening = None
            self._dot_look(key)
            return
        self._listening = key
        usage.used("voice-background-hear")
        if was is not None:
            self._dot_look(was)
        self._dot_look(key)

        def prepare():
            try:
                x = backdrop.generate(key, LISTEN_S)
                n = min(len(x), int(0.3 * backdrop.SR))
                ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
                x[:n] *= ramp
                x[-n:] *= ramp[::-1]
                data = np.stack([x, x], 1)
            except Exception:  # noqa: BLE001 - a missing asset doesn't stop the popup
                log.warning("background preview couldn't be loaded: %s", key, exc_info=True)
                data = None
            try:
                self.preview_ready.emit(gen, key, data)
            except RuntimeError:  # the owner was deleted while the file loaded
                pass
        threading.Thread(target=prepare, name="background-preview", daemon=True).start()

    def _preview_done(self, gen: int, key: str, data):
        if gen != self._preview_gen or self._listening != key or not self.isVisible():
            return
        engine = getattr(self.panel.window(), "engine", None)
        if data is None or engine is None:
            self._heard(key)
            return
        engine.play(LISTEN_SID, data, LISTEN_GAIN, mode="restart", preview=True)
        QTimer.singleShot(int(LISTEN_S * 1000) + 100, self,
                          lambda g=gen, k=key: g == self._preview_gen and self._heard(k))

    def _heard(self, key: str):
        """Its few seconds are over: the dot is a ▶ again."""
        if self._listening == key:
            self._listening = None
            self._dot_look(key)

    def hideEvent(self, e):
        self._preview_gen += 1
        engine = getattr(self.panel.window(), "engine", None)
        if engine is not None and self._listening is not None:
            engine.stop(LISTEN_SID)   # closed: the sample goes with it
        self._listening = None
        super().hideEvent(e)

    # ------------------------------------------------------------- actions
    def _add(self, key: str, button: QPushButton):
        if key == "sound":
            m = self.panel.board_sound_menu()
            if m is None:
                return
            picked = m.exec(button.mapToGlobal(QPoint(0, button.height())))
            m.deleteLater()
            if picked is not None:   # its row shows once the sound's loop is made
                QTimer.singleShot(300, self, lambda: self.isVisible() and self._again())
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
        place_over(self, under)
