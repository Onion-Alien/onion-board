"""Marks a tab whose feature is live right now (Sounds while a sound plays, Voice
while the voice changer is changing your mic, Radio while a station plays, Apps
while a program's sound is sent, Triggers while the screen is watched), so it
can't be left on by accident without you noticing from another tab.

The mark is a small green badge drawn into the tab's icon, so a tab never changes
size when it goes live (a dot beside the name used to widen it and shove the tabs
after it along). Settings → Appearance can also tint live tabs green: a soft wash
over the tab and a green icon."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QTabBar, QTabWidget, QWidget

from soundboard import theme
from soundboard.ui import icons

TINT_ICON = "ok_text"   # a tinted live tab's icon: the theme's "ok" green


def live_color() -> str:
    """The live green: the theme's "ok" colour (the light themes darken it so it can
    be read)."""
    return theme.status("ok")


class LiveTint(QWidget):
    """The green wash over a bar's live tabs: a see-through child laid over the whole
    bar, so it takes no room and clicks go straight through to the tabs."""

    ALPHA = 0.14

    def __init__(self, bar: QTabBar):
        super().__init__(bar)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setGeometry(bar.rect())
        bar.installEventFilter(self)

    def eventFilter(self, obj: QObject, e: QEvent) -> bool:
        if obj is self.parentWidget() and e.type() == QEvent.Resize:
            self.setGeometry(obj.rect())
        return False

    def paintEvent(self, _e):
        bar = self.parentWidget()
        color = QColor(live_color())
        color.setAlphaF(self.ALPHA)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        for i in range(bar.count()):
            if _live(bar, i):
                p.drawRoundedRect(bar.tabRect(i).adjusted(1, 2, -1, 0), 6, 6)


def _live(bar: QTabBar, index: int) -> bool:
    return bool(bar.property(f"_live{index}"))


def _tinted(tabs: QTabWidget) -> bool:
    return bool(tabs.property("_live_tint"))


def _show(tabs: QTabWidget, index: int, icon: str | None):
    """Draw tab `index` as it is now: badge (and tint) while live, plain when not."""
    on = _live(tabs.tabBar(), index)
    name = icon or icons.tab_icon_name(tabs, index)
    if name:
        icons.set_tab_icon(tabs, index, name, TINT_ICON if on and _tinted(tabs) else None,
                           badge=on)


def _sync_tint(tabs: QTabWidget):
    bar = tabs.tabBar()
    wash = bar.findChild(LiveTint)
    want = _tinted(tabs) and any(_live(bar, i) for i in range(bar.count()))
    if want and wash is None:
        wash = LiveTint(bar)
    if wash is not None:
        wash.setVisible(want)
        wash.raise_()
        wash.update()


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
    tabs.setTabToolTip(index, f"{tip}\n{base}" if on and tip else base)
    _sync_tint(tabs)


def set_tint(tabs: QTabWidget, on: bool):
    """Also tint live tabs green (Settings → Appearance), or go back to the badge only."""
    tabs.setProperty("_live_tint", bool(on))
    for i in range(tabs.count()):
        if _live(tabs.tabBar(), i):
            _show(tabs, i, None)
    _sync_tint(tabs)


def is_tab_live(tabs: QTabWidget, index: int) -> bool:
    return _live(tabs.tabBar(), index)
