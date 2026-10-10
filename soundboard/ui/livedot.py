"""Marks a tab whose feature is live right now (Sounds while a sound plays, Voice
while the voice changer is changing your mic, Radio while a station plays, Apps
while a program's sound is sent, Triggers while the screen is watched), so it
can't be left on by accident without you noticing from another tab.

Two ways to mark it (Settings → Appearance): a tint, the default (a bar beside the
tab on the rail, ui/sidebar.py, and a coloured icon), or a small dot drawn into the
tab's icon. Both use the theme's "live" colour (its accent)."""
from __future__ import annotations

from PySide6.QtWidgets import QTabBar, QTabWidget

from soundboard import theme
from soundboard.ui import icons

TINT_ICON = "live_text"   # a tinted live tab's icon: the theme's live colour


def live_color() -> str:
    """The theme's live colour, as it reads on the background."""
    return theme.T["live_text"]


def _live(bar: QTabBar, index: int) -> bool:
    return bool(bar.property(f"_live{index}"))


def _tinted(tabs: QTabWidget) -> bool:
    return bool(tabs.property("_live_tint"))


def _show(tabs: QTabWidget, index: int, icon: str | None):
    """Draw tab `index` as it is now: tinted (or with the dot) while live, plain when
    not. The two are either-or: a tinted tab gets no dot."""
    on = _live(tabs.tabBar(), index)
    tint = on and _tinted(tabs)
    name = icon or icons.tab_icon_name(tabs, index)
    if name:
        icons.set_tab_icon(tabs, index, name, TINT_ICON if tint else None,
                           badge=on and not tint)


def set_tab_live(tabs: QTabWidget, index: int, on: bool, tip: str = "",
                 icon: str | None = None):
    """Mark (or unmark) a tab as live and put `tip` in front of its tooltip while it
    is. `icon` names the tab's icon (default: the one it already has)."""
    tabs.tabBar().setProperty(f"_live{index}", bool(on))
    _show(tabs, index, icon)
    base = tabs.property(f"_tip{index}")
    if base is None:
        base = tabs.tabToolTip(index)
        tabs.setProperty(f"_tip{index}", base)
    tabs.setTabToolTip(index, "\n".join(filter(None, (tip, base))) if on and tip else base)


def set_tint(tabs: QTabWidget, on: bool):
    """Mark live tabs with the bar and a coloured icon (True, the default) or the dot
    (Settings → Appearance)."""
    tabs.setProperty("_live_tint", bool(on))
    for i in range(tabs.count()):
        if _live(tabs.tabBar(), i):
            _show(tabs, i, None)


def is_tab_live(tabs: QTabWidget, index: int) -> bool:
    return _live(tabs.tabBar(), index)
