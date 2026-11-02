"""Part of the voice changer (ui/voice/voicefxpanel.py `VoiceFxPanel`): the effect cards: what's on
top of the voice (the board sounds behind it), the delay it adds, new effect types, folding
the cards and laying them out in their tabs' two columns."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QWidget

from soundboard import voicefx
from soundboard.i18n import _, ngettext
from soundboard.ui.kit.widgets import take_out
from soundboard.ui.voice.effectrow import CALLERS, EffectRow, GROUPS, HERO

if TYPE_CHECKING:
    from typing import Any

    _Base = QWidget
else:
    _Base = object


class VoiceFxCards(_Base):
    if TYPE_CHECKING:   # what VoiceFxPanel has that these use
        _delay_cache: Any
        _device_ms: Any
        _edited: Any
        _emit: Any
        _extras: Any
        _folded_fx: Any
        _fx_cols: Any
        _pages: Any
        _placed: Any
        _preview: Any
        _refresh: Any
        _replace: Any
        _spec_effects: Any
        btn_effects: Any
        btn_power: Any
        delay: Any
        effects_pop: Any
        folds_changed: Any
        hero_box: Any
        more: Any
        rows: Any
        sound_list: Any

    # ------------------------------------------------------------------ the window
    DLG_SIZE = QSize(660, 720)

    def _backdrop_row(self):
        """The Background's card (None before it's made, or an add-on took its place)."""
        from soundboard.ui.voice.backdroprow import BackdropRow
        row = self.rows.get("backdrop")
        return row if isinstance(row, BackdropRow) else None

    def open_effects(self, under: QWidget | None = None):
        """The Effects pop-up, over the voice bar's button (or `under`: the AI voice's)."""
        if self.effects_pop is None:
            from soundboard.ui.voice.effectspopup import EffectsPopup
            self.effects_pop = EffectsPopup(self)  # pyright: ignore[reportArgumentType]  (a VoiceFxPanel)
        self.effects_pop.open_for(under or self.btn_effects)

    def on_top_state(self) -> dict:
        """What the Effects pop-up shows: {"layers": {layer: level}, "sounds": [(id,
        name, level)], "extras": {type: its slider's value}} (only what's on)."""
        from soundboard.ui.voice.effectspopup import EXTRAS
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
            from soundboard.ui.voice.effectspopup import EXTRAS
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

    def set_device_delay(self, ms: float | None):
        """Your sound devices' own delay (mic in + send device out), from the engine."""
        if ms != self._device_ms:
            self._device_ms = ms
            self._show_delay()

    def effects_delay(self) -> float:
        """Milliseconds the effects that are on add (worked out from their settings, so
        it's known before the mic has sent anything)."""
        if not self.btn_power.isChecked() and self._preview is None:
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
        on = self.btn_power.isChecked() or self._preview is not None
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

    def add_new_effects(self):
        """Add cards for effect types registered since (modules loaded later)."""
        added = False
        for etype, cls in voicefx.REGISTRY.items():
            if etype in self.rows or cls.extra:   # (the extras live in the Effects pop-up)
                continue
            cfg = self._spec_effects.get(etype) or {}
            if etype == "backdrop":
                from soundboard.ui.voice.backdroprow import BackdropRow
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
        for title in self._pages:
            types = dict(GROUPS).get(title) or [t for t in self.rows if t not in grouped]
            out.append((title, [self.rows[t] for t in types if t in self.rows
                                and (t not in CALLERS or self.rows[t].chk.isChecked())]))
        return out

    @staticmethod
    def _card_height(c: QWidget, width: int) -> int:
        return c.heightForWidth(width) if c.hasHeightForWidth() else c.sizeHint().height()

    def _place_cards(self):
        """Each tab's cards into its columns: one column, or two with each card under
        whichever column is shorter so far (in reading order), so a short card never
        leaves a hole beside a tall one. A tab with no cards (Add-ons) is hidden."""
        plans = {}
        for title, cards in self._ordered_cards():
            if self._fx_cols == 1:
                plan = [list(cards), []]
            else:
                room = self.more.width() - 4
                width = max(200, (room - self._pages[title][1].spacing()) // 2)
                plan, heights = [[], []], [0, 0]
                for c in cards:
                    i = 0 if heights[0] <= heights[1] else 1
                    plan[i].append(c)
                    heights[i] += self._card_height(c, width) + 10
            plans[title] = plan
        if plans != self._placed:
            self._placed = plans
            for title, plan in plans.items():
                scroll, row, cols = self._pages[title]
                for col in cols:
                    while col.count() > 1:           # all but the stretch
                        take_out(col)
                for col, widgets in zip(cols, plan):
                    for w in widgets:
                        col.insertWidget(col.count() - 1, w)   # above the column's stretch
                row.setStretch(1, 1 if self._fx_cols == 2 else 0)
                self.more.setTabVisible(self.more.indexOf(scroll), any(plan))
        # an animal left out stays on its tab's page, hidden (taken out, it would still
        # be drawn there; never placed, it has no parent and would show as a window)
        for title, types in GROUPS:
            for t in types:
                if t in CALLERS and t in self.rows:
                    r = self.rows[t]
                    if r.parentWidget() is None:
                        r.setParent(self._pages[title][0].widget())
                    r.setVisible(r.chk.isChecked())
        self._count_tabs()

    def _count_tabs(self):
        """Each group's tab says how many of its effects are on, so none is missed
        behind another tab (Main is the first one seen: no count)."""
        for title, cards in self._ordered_cards():
            scroll = self._pages[title][0]
            n = sum(c.chk.isChecked() for c in cards)
            text = (ngettext("{group}  ·  {n} on", "{group}  ·  {n} on", n, group=title)
                    if n else title)
            i = self.more.indexOf(scroll)
            if self.more.tabText(i) != text:
                self.more.setTabText(i, text)

    def _reshape(self):
        """A card got taller or shorter (on/off, folded): balance the columns again
        (an animal switched on or off also comes or goes, in one column too)."""
        self._replace.start()
