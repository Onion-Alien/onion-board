"""The voice changer's Background card (voicefx.builtin.Background) and its pop-up.

A row per built-in sound (rain, wind...) with its level and a "Speed and pitch"
button; under them the sounds picked from your board, each with the same; then
"Only while I talk". The button opens `TweakPopup`, a small Live controls for that
one sound: speed, pitch, bass, muffle, reverb and a few places it can seem to be.

The levels are the effect's own numbers; the pop-ups' settings and the board sounds
are its other settings ("tweaks", "sounds": voicefx.backdrop), which the voice
changer's spec carries the same way, so saved voices keep them.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QGridLayout, QHBoxLayout, QLabel,
                               QMenu, QPushButton, QVBoxLayout, QWidget)

from soundboard import voicefx
from soundboard.i18n import _
from soundboard.ui.kit import fit, icons
from soundboard.ui.kit.panel import hint_label, reset_button
from soundboard.ui.voice.voicefxpanel import EffectRow, ParamSlider
from soundboard.voicefx import Param, backdrop

VAL_W = 52
GAP = 10


def _row_slider(q: Param, value: float, name_w: int, centred: bool = False) -> ParamSlider:
    """A one-line slider (name | track | value) with a fixed name column, so the rows
    line up (like Live controls')."""
    s = ParamSlider(q, value, centred=centred)
    h = s.layout()
    assert h is not None   # name, slider, value
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(GAP)
    s.name.setFixedWidth(name_w)
    s.val.setObjectName("")
    s.val.setFixedWidth(VAL_W)
    return s


def place_names() -> dict[str, str]:
    return {"Far away": _("Far away"), "Next room": _("Next room"),
            "Through a wall": _("Through a wall"), "Outside": _("Outside"),
            "Bass boosted": _("Bass boosted")}


def tweak_labels() -> dict[str, str]:
    return {"speed": _("Speed"), "pitch": _("Pitch"), "bass": _("Bass"),
            "muffle": _("Muffle"), "reverb": _("Reverb")}


class TweakPopup(QDialog):
    """Speed, pitch, bass, muffle and reverb for one background sound, over the card
    beside its button. `changed(key, tweaks)` on every move; a click outside or
    Escape closes it."""
    changed = Signal(str, dict)

    def __init__(self, parent: QWidget):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        fit.watch(self)
        self.setProperty("popover", True)
        self.setObjectName("transport")
        self.key = ""
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.title = QLabel()
        self.title.setObjectName("section")
        head.addWidget(self.title)
        sub = hint_label(_("Background"))
        head.addWidget(sub)
        head.addStretch(1)
        self.btn_reset = reset_button(_("Back to 1x, no pitch change and no effects"))
        self.btn_reset.clicked.connect(lambda: self._apply(backdrop.neutral_tweaks()))
        head.addWidget(self.btn_reset)
        v.addLayout(head)
        labels = tweak_labels()
        w = max(self.fontMetrics().horizontalAdvance(t) for t in labels.values()) + 6
        self.sliders: dict[str, ParamSlider] = {}
        for q in backdrop.TWEAKS:
            q = Param(q.key, labels[q.key], q.lo, q.hi, q.default, q.unit, q.step)
            s = _row_slider(q, q.default, w, centred=q.key in ("speed", "pitch", "bass"))
            s.changed.connect(self._moved)
            self.sliders[q.key] = s
            v.addWidget(s)
        grid = QGridLayout()
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)
        for i, (name, shown) in enumerate(place_names().items()):
            b = QPushButton(shown)
            b.setObjectName("small")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _on=False, n=name: self._place(n))
            grid.addWidget(b, i // 3, i % 3)
        v.addLayout(grid)
        self.setMinimumWidth(380)

    def tweaks(self) -> dict:
        return {k: s.value() for k, s in self.sliders.items()}

    def _apply(self, t: dict):
        for k, s in self.sliders.items():
            s.blockSignals(True)
            s.set_value(t.get(k, s.q.default))
            s.blockSignals(False)
        self._moved()

    def _place(self, name: str):
        """A place: where it seems to be (bass, muffle, reverb); speed and pitch stay."""
        self._apply({**self.tweaks(), **backdrop.PLACES[name]})

    def _moved(self):
        self.btn_reset.setVisible(not backdrop.is_neutral(self.tweaks()))
        if self.key:
            self.changed.emit(self.key, self.tweaks())

    def open_for(self, key: str, title: str, tweaks: dict | None, under: QWidget):
        self.key = ""   # loading: no changed()
        self.title.setText(title)
        self._apply(backdrop.clean_tweaks(tweaks))
        self.key = key
        self.adjustSize()
        pos = under.mapToGlobal(QPoint(0, under.height() + 4))
        screen = (QApplication.screenAt(pos) or under.screen()).availableGeometry()
        x = min(max(screen.left(), pos.x() + under.width() - self.width()),
                screen.right() - self.width() + 1)
        y = pos.y()
        if y + self.height() > screen.bottom():
            y = under.mapToGlobal(QPoint(0, 0)).y() - self.height() - 4
        self.move(x, max(screen.top(), y))
        self.show()


class BackdropRow(EffectRow):
    """The Background card. `sounds()` lists the board's sounds as [(id, name,
    categories)] for "Add a sound from my board"."""

    def __init__(self, cls, cfg: dict, sounds: Callable[[], list] = list):
        self._sounds = sounds
        super().__init__(cls, cfg)

    # ------------------------------------------------------------- building
    def _fill(self, grid: QGridLayout, cfg: dict):
        extra = backdrop.clean_extra(cfg)
        self.tweaks: dict[str, dict] = dict(extra.get("tweaks", {}))
        self.picked: list[dict] = [dict(d) for d in extra.get("sounds", [])]
        self.pop: TweakPopup | None = None
        self.tweak_buttons: dict[str, QPushButton] = {}
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        levels = [q for q in self.cls.params if q.key in backdrop.LAYERS]
        fm = self.fontMetrics()
        self.name_w = max(fm.horizontalAdvance(voicefx.shown(q.label)) for q in levels) + 8
        for q in levels:
            s = _row_slider(q, cfg.get(q.key, q.default), self.name_w)
            s.changed.connect(self._slid)
            self.sliders.append(s)
            box.addLayout(self._with_button(s, q.key, voicefx.shown(q.label)))
        mine = hint_label(_("From my board"))
        mine.setObjectName("fxparam")
        box.addSpacing(4)
        box.addWidget(mine)
        self.mine_box = QVBoxLayout()
        self.mine_box.setContentsMargins(0, 0, 0, 0)
        self.mine_box.setSpacing(6)
        self._mine_rows: list[QWidget] = []
        box.addLayout(self.mine_box)
        self.btn_add = QPushButton(_("Add a sound from my board"))
        self.btn_add.setProperty("quiet", True)
        icons.set_icon(self.btn_add, "plus", size=14)
        self.btn_add.clicked.connect(self._add_menu)
        add_row = QHBoxLayout()
        add_row.addWidget(self.btn_add)
        add_row.addStretch(1)
        box.addLayout(add_row)
        talk = next(q for q in self.cls.params if q.key == "talk")
        s = ParamSlider(talk, cfg.get(talk.key, talk.default), compact=False)
        s.changed.connect(self._slid)
        self.sliders.append(s)
        box.addWidget(s)
        holder = QWidget()
        holder.setLayout(box)
        grid.addWidget(holder, 0, 0)
        grid.setColumnStretch(0, 1)
        self._fill_mine()

    def _with_button(self, s: ParamSlider, key: str, title: str,
                     remove: Callable[[], None] | None = None) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setSpacing(8)
        h.addWidget(s, 1)
        b = QPushButton(_("Speed and pitch"))
        b.setObjectName("small")
        b.setCheckable(True)    # lit while that sound's speed, pitch or sound is changed
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setToolTip(_("Speed, pitch, bass and where “{sound}” seems to be", sound=title))
        b.clicked.connect(lambda _on=False, k=key, t=title, btn=b: self._open_pop(k, t, btn))
        self.tweak_buttons[key] = b
        h.addWidget(b)
        if remove is not None:
            x = QPushButton()
            x.setProperty("quiet", True)
            tip = _("Take “{sound}” out of the background", sound=title)
            x.setToolTip(tip)
            x.setAccessibleName(tip)
            icons.close_button(x, 24)   # a fixed 24 px square (a dense row's size)
            x.clicked.connect(remove)
            h.addWidget(x)
        else:   # the ✕'s room, so every row's slider and value line up
            h.addSpacing(24 + h.spacing())
        self._light(key)
        return h

    def _fill_mine(self):
        """The board sounds' rows, built again from self.picked."""
        for w in self._mine_rows:      # each row is one widget: no layout walking
            self.mine_box.removeWidget(w)
            w.deleteLater()
        self._mine_rows = []
        for k in [k for k in self.tweak_buttons if k.startswith("sound:")]:
            del self.tweak_buttons[k]
        names = {sid: name for sid, name, _cats in self._list()}
        fm = self.fontMetrics()
        for d in self.picked:
            sid = d["id"]
            name = names.get(sid) or _("Sound not found")
            q = Param("level", fm.elidedText(name, Qt.TextElideMode.ElideRight, self.name_w - 4),
                      0, 1, 0.5)
            s = _row_slider(q, d.get("level", 0.5), self.name_w)
            s.setToolTip(name)
            s.changed.connect(lambda sl=s, i=sid: self._level(i, sl.value()))
            row = QWidget()
            lay = self._with_button(s, "sound:" + sid, name,
                                    remove=lambda _on=False, i=sid: self._remove(i))
            lay.setContentsMargins(0, 0, 0, 0)
            row.setLayout(lay)
            self.mine_box.addWidget(row)
            self._mine_rows.append(row)
        self.btn_add.setVisible(len(self.picked) < backdrop.MAX_SOUNDS)

    def _list(self) -> list:
        try:
            return list(self._sounds() or [])
        except Exception:  # noqa: BLE001 - no board yet: nothing to pick
            return []

    # ------------------------------------------------------------- actions
    def _light(self, key: str):
        b = self.tweak_buttons.get(key)
        if b is not None:
            b.setChecked(not backdrop.is_neutral(self._tweaks_of(key)))

    def _tweaks_of(self, key: str) -> dict:
        if key.startswith("sound:"):
            sid = key[len("sound:"):]
            return next((d.get("tweaks", {}) for d in self.picked if d["id"] == sid), {})
        return self.tweaks.get(key, {})

    def _open_pop(self, key: str, title: str, btn: QPushButton):
        self._light(key)   # the click toggled it: it shows "changed", not "open"
        if self.pop is None:
            self.pop = TweakPopup(self.window())
            self.pop.changed.connect(self._tweaked)
        self.pop.open_for(key, title, self._tweaks_of(key), btn)

    def _tweaked(self, key: str, t: dict):
        keep = {} if backdrop.is_neutral(t) else backdrop.clean_tweaks(t)
        if key.startswith("sound:"):
            sid = key[len("sound:"):]
            for d in self.picked:
                if d["id"] == sid:
                    if keep:
                        d["tweaks"] = keep
                    else:
                        d.pop("tweaks", None)
        elif keep:
            self.tweaks[key] = keep
        else:
            self.tweaks.pop(key, None)
        self._light(key)
        self._slid()

    def _level(self, sid: str, v: float):
        for d in self.picked:
            if d["id"] == sid:
                d["level"] = v
        self._slid()

    def _remove(self, sid: str):
        self.picked = [d for d in self.picked if d["id"] != sid]
        self._fill_mine()
        self._slid()
        self.reshaped.emit()

    def _add(self, sid: str):
        if len(self.picked) >= backdrop.MAX_SOUNDS or any(d["id"] == sid for d in self.picked):
            return
        self.picked.append({"id": sid, "level": 0.5})
        self._fill_mine()
        self._slid()
        self.reshaped.emit()

    def _add_menu(self):
        m = self.add_menu()
        m.exec(self.btn_add.mapToGlobal(QPoint(0, self.btn_add.height())))
        m.deleteLater()

    def add_menu(self) -> QMenu:
        """The board's sounds to pick from (by category when it has them)."""
        m = QMenu(self)
        picked = {d["id"] for d in self.picked}
        sounds = [(sid, name, cats) for sid, name, cats in self._list() if sid not in picked]
        if not sounds:
            a = m.addAction(_("No sounds on your board yet") if not self._list()
                            else _("Every sound is in already"))
            a.setEnabled(False)
        else:
            cats = sorted({c for _s, _n, cs in sounds for c in cs}, key=str.casefold)
            if cats:
                for c in cats:
                    sub = m.addMenu(c)
                    for sid, name, cs in sorted(sounds, key=lambda s: s[1].casefold()):
                        if c in cs:
                            sub.addAction(name, lambda i=sid: self._add(i))
                rest = [s for s in sounds if not s[2]]
                if rest:
                    sub = m.addMenu(_("Not in a category"))
                    for sid, name, _c in sorted(rest, key=lambda s: s[1].casefold()):
                        sub.addAction(name, lambda i=sid: self._add(i))
            else:
                for sid, name, _c in sorted(sounds, key=lambda s: s[1].casefold()):
                    m.addAction(name, lambda i=sid: self._add(i))
        return m

    # ------------------------------------------------------------- state
    def state(self) -> dict:
        d = super().state()
        if self.tweaks:
            d["tweaks"] = {k: dict(v) for k, v in self.tweaks.items()}
        if self.picked:
            d["sounds"] = [dict(p) for p in self.picked]
        return d

    def load(self, cfg: dict | None):
        extra = backdrop.clean_extra(cfg or {})
        self.tweaks = dict(extra.get("tweaks", {}))
        self.picked = [dict(d) for d in extra.get("sounds", [])]
        super().load(cfg)
        for k in list(self.tweak_buttons):
            self._light(k)
        self._fill_mine()

    def refresh_names(self):
        """The board changed (a sound renamed or deleted): its row's name again."""
        self._fill_mine()
