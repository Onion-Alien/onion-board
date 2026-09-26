"""A glowing, gently pulsing dot that marks a tab whose feature is live right now
(e.g. the Voice tab while the voice changer is changing your mic), so it can't be
left on by accident without you noticing from another tab."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import QTabBar, QTabWidget, QWidget

from soundboard.ui import icons

GREEN = "#13ce66"   # the same green as the voice changer's ON switch


class LiveDot(QWidget):
    """A green dot with a soft halo that breathes (the halo, not the dot, so it
    stays readable). Animation runs only while the dot is shown."""

    SIZE = 20

    def __init__(self, color: str = GREEN, parent: QWidget | None = None):
        super().__init__(parent)
        self._color = QColor(color)
        self._glow = 1.0
        self.setFixedSize(QSize(self.SIZE, self.SIZE))
        self.setAttribute(Qt.WA_TransparentForMouseEvents)   # clicks go to the tab
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(1400)
        self._anim.setStartValue(1.0)
        self._anim.setKeyValueAt(0.5, 0.25)
        self._anim.setEndValue(1.0)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._set_glow)

    def _set_glow(self, v):
        self._glow = float(v)
        self.update()

    def showEvent(self, e):
        self._anim.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._anim.stop()
        super().hideEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        halo = QRadialGradient(c, self.SIZE / 2)
        inner = QColor(self._color)
        inner.setAlphaF(0.75 * self._glow)
        outer = QColor(self._color)
        outer.setAlphaF(0.0)
        halo.setColorAt(0.3, inner)
        halo.setColorAt(1.0, outer)
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(c, self.SIZE / 2, self.SIZE / 2)
        p.setBrush(self._color)
        p.drawEllipse(c, 4, 4)


def set_tab_live(tabs: QTabWidget, index: int, on: bool, tip: str = "",
                 icon: str | None = None):
    """Show (or remove) a LiveDot on a tab, and put `tip` in front of its tooltip
    while it's live. `icon` names the tab's icon, turned green while live."""
    if icon:
        icons.set_tab_icon(tabs, index, icon, GREEN if on else None)
    bar = tabs.tabBar()
    dot = bar.tabButton(index, QTabBar.RightSide)
    base = tabs.property(f"_tip{index}")
    if base is None:
        base = tabs.tabToolTip(index)
        tabs.setProperty(f"_tip{index}", base)
    if on:
        if not isinstance(dot, LiveDot):
            dot = LiveDot()
            bar.setTabButton(index, QTabBar.RightSide, dot)
        dot.show()
        tabs.setTabToolTip(index, f"{tip}\n{base}" if tip else base)
    else:
        if isinstance(dot, LiveDot):
            bar.setTabButton(index, QTabBar.RightSide, None)
            dot.deleteLater()
        tabs.setTabToolTip(index, base)


def is_tab_live(tabs: QTabWidget, index: int) -> bool:
    return isinstance(tabs.tabBar().tabButton(index, QTabBar.RightSide), LiveDot)
