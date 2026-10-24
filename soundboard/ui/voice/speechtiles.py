"""The Languages card's language cards: their pictures, chips, favorites and the cards /
list view. Mixed into SpeechPanel (speechpanel.py)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from soundboard.core import langnames
from soundboard.ui.kit import theme
from soundboard.speech import translation
from soundboard.ui.voice.groupbar import no_match
from soundboard.ui.voice.voicefxpanel import (LIST_MIN_W, MAX_COLS, TILE_ART, TILE_GAP,
                                              TILE_MIN_W, VoiceTile)
from soundboard.i18n import _

if TYPE_CHECKING:
    class _Panel(QWidget):
        # what SpeechPanel itself provides, for the type checker only
        def __getattr__(self, name: str) -> Any: ...
else:
    _Panel = object


# the chips over the language cards
ALL, FAVS, READY = "", "favs", "ready"


def lang_icon(code: str, ready: bool, size: int = TILE_ART) -> QIcon:
    """A language card's picture: its code on a rounded square, a colour of its own
    once it's downloaded, grey until then (no flags: a language isn't a country)."""
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    hue = sum(ord(c) * (i + 7) for i, c in enumerate(code)) * 37 % 360
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor.fromHsv(hue, 140, 205) if ready else QColor(theme.T["groove"]))
    r = QRectF(1, 1, size - 2, size - 2)
    p.drawRoundedRect(r, size * 0.26, size * 0.26)
    f = QFont()
    f.setBold(True)
    f.setPixelSize(int(size * 0.38))
    p.setFont(f)
    p.setPen(QColor("white") if ready else QColor(theme.T["muted"]))
    p.drawText(r, Qt.AlignmentFlag.AlignCenter, code.split("-")[0].upper()[:3])
    p.end()
    return QIcon(pm)


class SpeechTiles(_Panel):
    """SpeechPanel's language cards."""

    # ---- the language cards
    def _fill_tiles(self):
        """(Re)make a card for each language: grey until it's downloaded."""
        for b in self._tile.values():
            self._tile_grid.removeWidget(b)
            b.hide()   # until it's gone it would paint over the regrown grid
            b.deleteLater()
        self._tile = {}
        for m in self.langs:
            code, name = m.language, langnames.of(m)
            b = VoiceTile(name)
            if self._listed:
                b.set_listed(True)
            b.setIcon(lang_icon(code, m.installed))
            b.setIconSize(QSize(TILE_ART, TILE_ART))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setProperty("missing", not m.installed)
            b.setToolTip(_("Others hear you in {language}.", language=name) if m.installed
                         else _("Not downloaded yet ({size} MB). Click to download it.",
                                size=translation.size_mb(m)))
            b.clicked.connect(lambda __=False, c=code: self._tile_clicked(c))
            b.star.setChecked(code in self._favs)
            b.star.toggled.connect(lambda on, c=code: self.set_favorite(c, on))
            self._tile[code] = b
        self._place_tiles()
        self._mark_tiles()

    def _place_tiles(self):
        """The cards the picked chip shows: All under Downloaded / Not downloaded yet,
        else your favorites (in the order you starred them) or the downloaded ones."""
        g, cols = self._tile_grid, self._tile_cols
        for w in (*self._tile.values(), *self._heads.values()):
            g.removeWidget(w)
        ready = [m.language for m in self.langs if m.installed]
        rows: list[tuple[str, list[str]]]
        if self._group == ALL:
            rows = [(READY, ready), ("get", [m.language for m in self.langs
                                             if not m.installed])]
        elif self._group == FAVS:
            rows = [("", [c for c in self._favs if c in self._tile])]
        else:
            rows = [("", ready)]
        found = self.bar.text()
        if found:
            rows = [(k, [c for c in cs if self.bar.matches(self._tile[c].title, c)])
                    for k, cs in rows]
        shown: set[str] = set()
        r = 0
        for head, group in rows:
            if not group:
                continue
            if head:
                g.addWidget(self._heads[head], r, 0, 1, cols)
                r += 1
            for i, code in enumerate(group):
                g.addWidget(self._tile[code], r + i // cols, i % cols)
            r += (len(group) + cols - 1) // cols
            shown.update(group)
        for k, lbl in self._heads.items():
            lbl.setVisible(self._group == ALL and any(
                (READY if c in ready else "get") == k for c in shown))
        for code, b in self._tile.items():
            b.setVisible(code in shown)
        self.no_favs.setVisible(self._group == FAVS and not shown and not found)
        self.no_ready.setVisible(self._group == READY and not shown and not found)
        no_match(self.no_match, found, shown)
        for c in range(MAX_COLS):
            g.setColumnStretch(c, 1 if c < cols else 0)

    def _mark_tiles(self):
        """Light up the language that's on (a card's own click toggles it: undone here)."""
        on = self.cb_lang.currentData() or ""
        for code, b in self._tile.items():
            if b.isChecked() != (code == on):
                b.setChecked(code == on)

    def show_group(self, key: str):
        """Show one chip's languages (ALL, FAVS or READY)."""
        self._group = key
        self.bar.set_group(key)
        self._place_tiles()

    def _group_count(self, key: str) -> int:
        """How many languages a group holds (the dropdown's numbers)."""
        if key == FAVS:
            return sum(c in self._tile for c in self._favs)
        return sum(1 for m in self.langs if key == ALL or m.installed)

    @property
    def favorites(self) -> list[str]:
        return list(self._favs)

    def set_favorite(self, code: str, on: bool):
        """Star or unstar a language: Favorites lists them in the order you starred them."""
        if on == (code in self._favs):
            return
        if on:
            self._favs.append(code)
        else:
            self._favs.remove(code)
        b = self._tile.get(code)
        if b is not None and b.star.isChecked() != on:
            b.star.setChecked(on)
        if self._group == FAVS:
            self._place_tiles()
        self.s["lang_favorites"] = list(self._favs)
        self.changed.emit(dict(self.s))

    def _fit_width(self, width: int):
        """As many language cards a row as the width holds, at least one."""
        least = LIST_MIN_W if self._listed else TILE_MIN_W
        cols = max(1, min(MAX_COLS, (width + TILE_GAP) // (least + TILE_GAP)))
        if cols != self._tile_cols:
            self._tile_cols = cols
            self._place_tiles()

    def set_view(self, view: str):
        """Picture cards, or a list (the Voice tab keeps all three cards the same)."""
        self._listed = view == "list"
        self.view_toggle.set_view(view)
        for b in self._tile.values():
            b.set_listed(self._listed)
        self._tile_cols = 0
        self._fit_width(self.width())
