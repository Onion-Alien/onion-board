"""The top of Edit sound's Simple view: how long the sound is, and everything on it as a
chip with an × that takes it off (the trim or the joined splices, speed, pitch, each
knob, the boost, the equalizer, each effect, the voice). Simple shows only the few
controls people use, so anything set in Advanced or Live controls still shows here, and
comes off in one click."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from soundboard import voicefx
from soundboard.audio import livefx, soundfx
from soundboard.core import usage
from soundboard.i18n import _
from soundboard.sounds.library import original_length
from soundboard.ui.kit.panel import Flow

if TYPE_CHECKING:
    from soundboard.ui.sounds.dialogs import EffectsPanel


def items(eff: EffectsPanel) -> list[tuple[str, Callable[[], object]]]:
    """(what's on, a function that takes it off) for each setting off its default."""
    f = soundfx.clean(eff.fx())
    out: list[tuple[str, Callable[[], object]]] = []
    if f["joined"]:   # its splices back to back: × plays it whole again (they stay marked)
        out.append((f"{_('Splices')} {len(f['splices'])}",
                    lambda: eff.trim.set_joined(False)))   # (it says changed)
    elif soundfx.is_trimmed(f):
        end = soundfx.fmt_s(f["end"]) if f["end"] else soundfx.fmt_s(eff.trim.length)
        out.append((f"{_('Trim')} {soundfx.fmt_s(f['start'])}–{end}",
                    lambda: eff.trim.set_values(0.0, 0.0, emit=True)))
    if abs(f["speed"] - 1) >= 1e-3:
        out.append((eff.speed.text(), lambda: (eff._set_tuning(1.0, eff.pitch.value(), True),
                                               eff._edited())))
    if abs(f["pitch"]) >= 1e-3:
        out.append((f"{voicefx.shown(eff.pitch.q.label)} {eff.pitch.text()}",
                    lambda: (eff.pitch.set_value(0.0), eff._edited())))
    for q in livefx.PARAMS:
        k = eff.knobs[q.key]
        if q.key in eff.knob_values():
            out.append((f"{voicefx.shown(q.label)} {k.text()}",
                        lambda k=k: (k.set_value(0.0), eff._knobs_edited())))
    if abs(f["gain_db"]) >= 1e-3:
        out.append((f"{voicefx.shown(eff.boost.q.label)} {eff.boost.text()}",
                    lambda: (eff.boost.set_value(0.0), eff._edited())))
    if f["reverse"]:
        out.append((_("Play backwards"), lambda: eff.reverse.setChecked(False)))
    if any(abs(g) > 1e-6 for g in f["eq"]):
        out.append((_("Equalizer"), eff.eq_off))
    for etype, row in eff.rows.items():
        if row.chk.isChecked():
            out.append((voicefx.shown(row.cls.name),
                        lambda t=etype: eff.turn_on(t, False)))
    if f["voice"]:
        from soundboard.ui.sounds.voicepicker import describe
        out.append((describe(f["voice"]), lambda: eff.set_voice({})))
    return out


class Summary(QWidget):
    """The length, then a chip per setting that's on ("Effects: none" when nothing is)."""

    def __init__(self, eff: EffectsPanel):
        super().__init__()
        self.eff = eff
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        self.length = QLabel()
        self.length.setObjectName("muted")
        self.length.setToolTip(_("Length"))
        h.addWidget(self.length, 0, Qt.AlignmentFlag.AlignVCenter)
        self.box = QWidget()
        self.box.setObjectName("spcol")   # on the page, no box of its own
        self.box.setStyleSheet("QWidget#spcol { background:transparent; }")
        self.flow = Flow(self.box, gap=6)
        h.addWidget(self.box, 1, Qt.AlignmentFlag.AlignVCenter)   # level with the length
        self.none = QLabel(_("Effects: {s}", s=_("none")), self.box)   # (a parent: shown
        self.none.setObjectName("muted")                                # alone, a window)
        self.none.hide()
        self.chips: list[QPushButton] = []
        eff.changed.connect(self.refresh)
        self.refresh()

    def set_sound(self, meta):
        n = original_length(meta) if meta is not None else 0.0
        self.length.setText(soundfx.fmt_s(n) if n > 0 else "")
        self.length.setVisible(n > 0)
        self.refresh()

    def refresh(self):
        for b in self.chips:   # (hidden at once: until it's deleted it still drew,
            self.flow.removeWidget(b)   # stretched over the row)
            b.hide()
            b.deleteLater()
        self.chips = []
        self.flow.removeWidget(self.none)
        got = items(self.eff)
        for text, off in got:
            b = QPushButton(f"{text}  ×")   # (the × after the words, as on a tab)
            b.setObjectName("small")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            tip = _("Take “{effect}” off", effect=text)
            b.setToolTip(tip)
            b.setAccessibleName(tip)
            b.clicked.connect(lambda __=False, off=off: (usage.used("edit-summary-off"), off()))
            self.flow.addWidget(b)
            self.chips.append(b)
        if not got:
            self.flow.addWidget(self.none)
        self.none.setVisible(not got)
