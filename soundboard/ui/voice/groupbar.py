"""The bar over the voice cards on the Voice changer, AI voices and Languages tabs:
which group shows (a dropdown), a search box and the cards / list switch, the same
shape and the same places on all three so they line up when you switch tabs.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget

from soundboard.i18n import _
from soundboard.ui.kit import icons
from soundboard.ui.kit.panel import ViewToggle
from soundboard.ui.kit.widgets import DropdownMenu, fit_placeholder

BAR_H = 32        # px: the dropdown, the search box and the view switch (26 + 2 * 3)
PICK_MIN_W = 190  # px: the dropdown's width, so the search box starts in one place
PICK_NARROW = 120  # px: its least, in a narrow window (the name ends in "…")


class GroupBar(QWidget):
    """`groups`: (key, name, icon) in menu order; a line goes after Favorites.
    `count(key)` says how many a group holds (shown in the menu, worked out as it opens);
    `hints`: the search box's grey words, longest first; `tip`: the dropdown's tooltip.
    `picked(key)` when a group is chosen, `searched(text)` as the search box changes."""
    picked = Signal(str)
    searched = Signal(str)

    def __init__(self, groups: list[tuple[str, str, str]], view_toggle: ViewToggle,
                 count: Callable[[str], int], hints: tuple[str, ...], tip: str):
        super().__init__()
        self._names = {k: t for k, t, _i in groups}
        self._icons = {k: i for k, t, i in groups}
        self._count = count
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        b = self.button = QPushButton()
        b.setObjectName("voicepick")
        b.setFixedHeight(BAR_H)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tip = tip   # the button's tip ("Which voices show")
        m = self.menu = DropdownMenu(b)
        m.setObjectName("voicepickmenu")
        self._acts: dict[str, QAction] = {}
        ag = QActionGroup(self)
        ag.setExclusive(True)
        for key, text, icon in groups:
            a = QAction(text.replace("&", "&&"), m)
            a.setCheckable(True)
            icons.set_icon(a, icon, "accent" if icon == "star_filled" else None)
            a.triggered.connect(lambda __=False, k=key: self._chosen(k))
            ag.addAction(a)
            m.addAction(a)
            self._acts[key] = a
            if key == "favs":
                m.addSeparator()
        m.aboutToShow.connect(self._counts)
        b.setMenu(m)
        h.addWidget(b, 0)

        s = self.search = QLineEdit()
        s.setObjectName("voicesearch")
        s.setFixedHeight(BAR_H)
        fit_placeholder(s, *hints)
        s.setAccessibleName(hints[-1])
        s.addAction(icons.icon("search", "muted"), QLineEdit.ActionPosition.LeadingPosition)
        icons.clear_button(s)
        s.textChanged.connect(lambda t: self.searched.emit(t.strip()))
        h.addWidget(s, 1)

        view_toggle.setFixedHeight(BAR_H)
        h.addWidget(view_toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        self._key: str | None = None
        self._fit_button()
        self.set_group(groups[0][0])

    def _fit_button(self):
        """As wide as the longest group name needs (icon, words, arrow), at least
        PICK_MIN_W: the button keeps one width whichever group shows. A narrow window
        gives it up to 40 % of the bar, so the search box keeps room to type."""
        fm = self.button.fontMetrics()
        words = max(fm.horizontalAdvance(t) for t in self._names.values())
        self._pick_w = max(PICK_MIN_W, words + 18 + 8 + 24 + 28)
        w = self._pick_w if self.width() <= 0 else min(
            self._pick_w, max(PICK_NARROW, int(self.width() * 0.4)))
        self.button.setFixedWidth(w)
        self._show_name()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_button()

    def _show_name(self):
        """The group's name on the button, ending in "…" when the button is narrow."""
        if self._key is None:
            return
        name = self._names[self._key]
        room = self.button.width() - 18 - 8 - 24 - 28
        shown = self.button.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, room)
        self.button.setText(shown.replace("&", "&&"))
        self.button.setToolTip(name if shown != name else self._tip)

    def _counts(self):
        """The menu's numbers, right-aligned in its shortcut column."""
        for key, a in self._acts.items():
            n = self._count(key)
            a.setText(f"{self._names[key].replace('&', '&&')}\t{n}")

    def _chosen(self, key: str):
        self.set_group(key)
        self.picked.emit(key)

    def set_group(self, key: str):
        """Show `key` as the chosen group (no signal)."""
        if key not in self._acts:
            return
        self._key = key
        self._acts[key].setChecked(True)
        b = self.button
        self._show_name()
        b.setAccessibleName(self._names[key])
        icon = self._icons[key]
        icons.set_icon(b, icon, "accent" if icon == "star_filled" else None, size=16)

    def choose(self, key: str):
        """Pick a group as a click in the menu would."""
        self._acts[key].trigger()

    def text(self) -> str:
        return self.search.text().strip()

    def matches(self, *words: str) -> bool:
        """Whether a card with these words (its name, its key) fits the search."""
        t = self.text().casefold()
        return not t or any(t in w.casefold() for w in words if w)


def no_match(label, found: str, shown) -> None:
    """The "nothing matches" line under the bar: shown while a search finds no card."""
    label.setVisible(bool(found) and not shown)
    if found and not shown:
        label.setText(_("Nothing matches “{text}”.", text=found))
