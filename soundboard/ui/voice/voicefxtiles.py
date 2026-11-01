"""Part of the voice changer (ui/voice/voicefxpanel.py `VoiceFxPanel`): the voice tiles: rolling
a random voice, hearing one, the tiles themselves and where they go (grid or list, in groups,
favourites, search matches)."""
from __future__ import annotations

import html
import random
import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QWidget

from soundboard import voicefx
from soundboard.core import errors, usage
from soundboard.i18n import _
from soundboard.speech import aipreview
from soundboard.ui.kit import busy, icons
from soundboard.ui.voice import art
from soundboard.ui.voice.aivoicebrowser import HEAR, MAKING
from soundboard.ui.voice.effectrow import on_top
from soundboard.ui.voice.groupbar import no_match
from soundboard.ui.voice.voicetiles import (
    ALL,
    CUSTOM,
    FAVS,
    MAX_COLS,
    MINE,
    TILE_ART,
    VOICE_GROUPS,
    VoiceTile,
    voice_group,
)

if TYPE_CHECKING:
    from typing import Any

    _Base = QWidget
else:
    _Base = object


class VoiceFxTiles(_Base):
    if TYPE_CHECKING:   # what VoiceFxPanel has that these use
        _custom: Any
        _emit: Any
        _favs: Any
        _fit_width: Any
        _group: Any
        _heads: Any
        _hearing: Any
        _listed: Any
        _parent: Any
        _preset: Any
        _end_preview: Any
        _refresh: Any
        _sampled: Any
        _saved_tiles: Any
        _shown: Any
        _tile: Any
        _tile_cols: Any
        _tile_grid: Any
        _tile_menu: Any
        bar: Any
        btn_bin: Any
        btn_power: Any
        btn_sample: Any
        no_favs: Any
        no_match: Any
        pick: Any
        play_sample: Any
        random_tile: Any
        rows: Any
        store: Any
        tiles: Any
        view_toggle: Any
        width: Any

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

    def _tile_clicked(self, name: str):
        """A voice card: that voice, on. The one that's on already: the voice changer
        off (a second click undoes the first, no hunting for the switch)."""
        self._end_preview()   # (Edit voice showing another voice: back to the one on)
        if self.btn_power.isChecked() and name == self._preset:
            self.btn_power.setChecked(False)   # its toggled handler applies it
            return
        self.pick(name)

    def _make_tile(self, name: str, title: str, pic, line_icon: str) -> VoiceTile:
        """A checkable voice card: its picture (ui/voice/art.py), else a line icon, with the
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
        b.clicked.connect(lambda __=False, n=name: self._tile_clicked(n))
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
        found = self.bar.text()
        if found:
            rows = [(k, [n for n in ns if self.bar.matches(self._tile[n].title, n)])
                    for k, ns in rows]
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
        rolls = not found and len(self._roll_pool(on="")) >= 2
        if rolls:
            g.addWidget(self.random_tile, last + last_n // cols, last_n % cols)
        self.random_tile.setVisible(rolls)
        for k, lbl in self._heads.items():
            lbl.setVisible(self._group == ALL and any(voice_group(n) == k for n in shown))
        for n, b in self._tile.items():
            b.setVisible(n in shown)
        self.no_favs.setVisible(self._group == FAVS and not shown and not found)
        no_match(self.no_match, found, shown)
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
        self.bar.set_group(key)
        self._place_tiles()

    def _group_count(self, key: str) -> int:
        """How many voices a group holds (the dropdown's numbers)."""
        names = [*voicefx.PRESETS, CUSTOM, *(n for n in self.store.voices if n in self._tile)]
        if key == ALL:
            return len(names)
        if key == FAVS:
            return sum(n in self._tile for n in self._favs)
        return sum(voice_group(n) == key for n in names)

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
