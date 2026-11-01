"""The tabs on the rail (ui/window/sidebar.py): the tab widget whose own bar is hidden
(SideTabs), one rail button per tab (RailTab), and the "New" pill on a tab or its
count of new things ("3 new", with an arrow while more are coming in: newsounds.py)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QSizePolicy, QStyle, QStyleOptionTabWidgetFrame,
                               QTabWidget, QToolButton)

from soundboard.ui.kit import theme
from soundboard.i18n import _, ngettext
from soundboard.ui.kit.panel import keep_focus_off
from soundboard.ui.kit.pixels import snap_to_pixels
from soundboard.ui.window.railsizes import ICON

if TYPE_CHECKING:
    from soundboard.ui.window.sidebar import SideRail


class SideTabs(QTabWidget):
    """A QTabWidget whose bar is never shown (the rail stands in for it), and that
    says when anything the rail shows has changed."""

    changed = Signal()
    # a tab was asked for, also the one already showing (MainWindow: Settings, shown in
    # the tabs' place, goes back to the tabs)
    picked = Signal()

    def __init__(self):
        super().__init__()
        self._bar = self.tabBar()
        self._bar.hide()
        self._bar.installEventFilter(self)
        # the hidden bar was the Tab key's stop after the rail: it can't take focus, so
        # Tab stuck on the rail's last button and never reached the page
        self.setFocusProxy(None)   # pyright: ignore[reportArgumentType]  # None clears it
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabBar().setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def eventFilter(self, obj: QObject, e: QEvent) -> bool:
        # never self.tabBar() here: the filter also sees the bar's last events while it
        # is being torn down, and asking for the bar then wrapped a freed object and
        # crashed the app (an access violation, 2.0.2)
        if obj is self._bar and e.type() == QEvent.Type.Show:
            self._bar.hide()   # QTabWidget shows it again when it lays itself out
        return False

    def heightForWidth(self, w: int) -> int:
        """Qt's sum (the page, the bar and the frame), for the page showing only. Qt
        asks every page, and on the Radio, Triggers and Voice tabs (the ones whose height
        follows their width) every resize step laid out the text of all of them again,
        the hidden tabs' too: ~10 frames a second while dragging the window's edge. The
        tabs that aren't showing still count in the window's smallest size."""
        page = self.currentWidget()
        if page is None or not page.hasHeightForWidth():
            return super().heightForWidth(w)
        opt = QStyleOptionTabWidgetFrame()
        self.initStyleOption(opt)
        opt.state = QStyle.StateFlag.State_None
        pad = self.style().sizeFromContents(QStyle.ContentsType.CT_TabWidget, opt,
                                            QSize(0, 0), self)
        corners = [c.sizeHint().height() for c in (self.cornerWidget(Qt.Corner.TopLeftCorner),
                                                    self.cornerWidget(Qt.Corner.TopRightCorner))
                   if c is not None]
        bar = max([self._bar.sizeHint().height(), *corners])   # (North, as here)
        return page.heightForWidth(w - pad.width()) + bar + pad.height()

    def setCurrentIndex(self, i):
        with keep_focus_off(self):
            super().setCurrentIndex(i)
        self.picked.emit()

    def setCurrentWidget(self, w):
        with keep_focus_off(self):
            super().setCurrentWidget(w)
        self.picked.emit()

    def move_to(self, i):
        """Another tab without `picked`: the app moving off a tab that's going away
        (switched off in Settings, which stays open), not someone asking for one."""
        with keep_focus_off(self):
            super().setCurrentIndex(i)

    # what changes a tab's look, all through here
    def setTabText(self, i, text):
        super().setTabText(i, text)
        self.changed.emit()

    def setTabToolTip(self, i, tip):
        super().setTabToolTip(i, tip)
        self.changed.emit()

    def setTabIcon(self, i, icon):   # a theme or highlight colour change (icons.retheme)
        super().setTabIcon(i, icon)
        self.changed.emit()

    def setTabVisible(self, i, on):
        super().setTabVisible(i, on)
        self.changed.emit()

    def tabInserted(self, i):
        super().tabInserted(i)
        self.changed.emit()

    def tabRemoved(self, i):
        super().tabRemoved(i)
        self.changed.emit()


class RailTab(QToolButton):
    """One tab on the rail. Paints the current tab's fill (a live one's mark is the
    rail's: SideRail.paintEvent; or, with Settings' dot, the dot in its icon)."""

    def __init__(self, rail: SideRail, index: int):
        super().__init__()
        self.rail, self.index = rail, index
        self._kbd_focus = False
        self._press_pos = None
        self._dragging = False
        self.setObjectName("railtab")
        self.setCheckable(True)   # (the rail checks the current one: see SideRail.sync)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(ICON, ICON))
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def paintEvent(self, e):
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.isChecked():   # the current tab: a soft accent fill under the icon
            self._fill(r, *theme.rail_tint())
        super().paintEvent(e)
        if self.is_new():
            self._paint_new()
        elif self.new_count() or self.is_coming():
            self._paint_count()
        if self.hasFocus() and self._kbd_focus:
            p = QPainter(self)
            snap_to_pixels(p)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(QColor(theme.T["accent"]), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, 8, 8)

    def focusInEvent(self, e):
        # Qt also focuses the first tab on startup: that isn't keyboard navigation.
        self._kbd_focus = e.reason() in (Qt.FocusReason.TabFocusReason,
                                         Qt.FocusReason.BacktabFocusReason,
                                         Qt.FocusReason.ShortcutFocusReason)
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e):
        self._kbd_focus = False
        super().focusOutEvent(e)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_pos = e.globalPosition().toPoint()
            self._dragging = False
        # TabFocus keeps the old tab focused after clicking another one.
        for b in self.rail.buttons:
            b._kbd_focus = False
            b.update()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press_pos is not None and e.buttons() & Qt.MouseButton.LeftButton:
            pos = e.globalPosition().toPoint()
            if (pos - self._press_pos).manhattanLength() >= QApplication.startDragDistance():
                self._dragging = True
                self.setDown(False)
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if self._dragging:
                self.rail.preview_move(self, self.rail.mapFromGlobal(pos))
                e.accept()
                return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            dragging = self._dragging
            self._press_pos = None
            self._dragging = False
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            if dragging:
                self.setDown(False)
                self.rail.finish_move(self, self.rail.mapFromGlobal(e.globalPosition().toPoint()))
                e.accept()
                return
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        """Up / down: the tab before / after it, as the arrows did on the old top bar
        (left / right too; mirrored, left is the next one)."""
        step = {Qt.Key.Key_Up: -1, Qt.Key.Key_Down: 1, Qt.Key.Key_Left: -1,
                Qt.Key.Key_Right: 1}.get(e.key())
        if step is None or e.modifiers() & ~Qt.KeyboardModifier.KeypadModifier:
            return super().keyPressEvent(e)
        if self.isRightToLeft() and e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            step = -step
        shown = [b for b in self.rail.buttons if b.isVisible()]
        if self in shown:
            b = shown[(shown.index(self) + step) % len(shown)]
            b.setFocus(Qt.FocusReason.TabFocusReason)
            b.click()

    def is_new(self) -> bool:
        return bool(self.rail.tabs.tabBar().property(f"_new{self.index}"))

    def _paint_new(self):
        """A small "New" pill (set_tab_new): shut, across the foot of the icon; open,
        at the end of the row."""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = QFont(self.font())
        f.setBold(True)
        f.setPixelSize(8 if not self.rail.is_open() else 10)
        p.setFont(f)
        text = _("New")
        fm = QFontMetrics(f)
        w, h = fm.horizontalAdvance(text) + 8, fm.height() + 1
        if self.rail.is_open():
            x = 8 if self.isRightToLeft() else self.width() - w - 8
            y = (self.height() - h) / 2
        else:
            x, y = (self.width() - w) / 2, self.height() - h - 1
        r = QRectF(x, y, w, h)
        p.setPen(QPen(QColor(theme.T["bg"]), 1.5))   # a thin gap from the icon under it
        p.setBrush(QColor(theme.T["accent"]))
        p.drawRoundedRect(r, h / 2, h / 2)
        p.setPen(QColor(theme.T["on_accent"]))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
        p.end()

    def new_count(self) -> int:
        return int(self.rail.tabs.tabBar().property(f"_count{self.index}") or 0)

    def is_coming(self) -> bool:
        return bool(self.rail.tabs.tabBar().property(f"_coming{self.index}"))

    def _paint_count(self):
        """How many new things (set_tab_count), and an arrow while more are coming in.
        Open: a pill at the end of the row ("3 new"). Shut: the number in a bubble on
        the icon's top corner, the arrow in one on its foot."""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n, coming, shut = self.new_count(), self.is_coming(), not self.rail.is_open()
        rtl = self.isRightToLeft()
        f = QFont(self.font())
        f.setBold(True)
        f.setPixelSize(9 if shut else 10)
        p.setFont(f)
        fm = QFontMetrics(f)
        h = fm.height() + 1
        arrow = h - 4   # the arrow's size in its pill / bubble
        edge = QPen(QColor(theme.T["bg"]), 1.5)   # a thin gap from the icon under it

        def pill(x: float, y: float, w: float) -> QRectF:
            r = QRectF(x, y, w, h)
            p.setPen(edge)
            p.setBrush(QColor(theme.T["accent"]))
            p.drawRoundedRect(r, h / 2, h / 2)
            return r

        def draw_arrow(x: float, y: float):
            """A bold down arrow over a line (the icon's thin one vanished this small)."""
            pen = QPen(QColor(theme.T["on_accent"]), 1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            cx, s = x + arrow / 2, arrow
            if shut:   # (the bubble's too small for the line under it: just the arrow)
                p.drawLine(QPointF(cx, y + 0.5), QPointF(cx, y + s - 1))
                p.drawPolyline([QPointF(cx - s * 0.36, y + s * 0.45), QPointF(cx, y + s - 1),
                                QPointF(cx + s * 0.36, y + s * 0.45)])
                return
            p.drawLine(QPointF(cx, y + 0.5), QPointF(cx, y + s * 0.62))
            p.drawPolyline([QPointF(cx - s * 0.3, y + s * 0.36), QPointF(cx, y + s * 0.66),
                            QPointF(cx + s * 0.3, y + s * 0.36)])
            p.drawLine(QPointF(x + 1, y + s - 0.5), QPointF(x + s - 1, y + s - 0.5))

        if shut:
            mid = self.width() / 2 + (-1 if rtl else 1) * ICON / 2   # the icon's corner
            if n:
                text = "99+" if n > 99 else str(n)
                w = max(h, fm.horizontalAdvance(text) + 6)
                # its start edge stays put and a longer number grows it towards the end,
                # placed so the widest ("99+") still fits inside the button
                widest = max(h, fm.horizontalAdvance("99+") + 6)
                if rtl:
                    end = max(mid + h / 2, widest + 1)
                    x = end - w
                else:
                    x = min(mid - h / 2, self.width() - widest - 1)
                r = pill(x, (self.height() - ICON) / 2 - h / 2 + 1, w)
                p.setPen(QColor(theme.T["on_accent"]))
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
            if coming:
                r = pill(min(mid - h / 2, self.width() - h - 1),
                         min((self.height() + ICON) / 2 - h / 2, self.height() - h - 1), h)
                draw_arrow(r.left() + 2, r.top() + 2)
            p.end()
            return
        # past 99, "99+ new" (as the shut rail's bubble): 99,000 ran over the tab's name
        text = ngettext("{n} new", "{n} new", min(n, 100), n="99+" if n > 99 else n) if n else ""
        tw = fm.horizontalAdvance(text)
        pad = 8 if text else 2
        w = pad + (arrow + (4 if text else 0) if coming else 0) + tw + (8 if text else 2)
        # its start edge stays put, just after the tab's name, and a bigger number grows
        # it towards the end (pushed back only if it would run off the row)
        after_icon = 1 + 6 + ICON + 4   # (border, padding, icon, gap)
        if rtl:   # mirrored, the name sits at the far side: it's beside the icon instead
            x = max(4, self.width() - after_icon - 8 - w)
        else:
            name_end = after_icon + self.fontMetrics().horizontalAdvance(self.text())
            x = min(name_end + 8, self.width() - 4 - w)
        r = pill(x, (self.height() - h) / 2, w)
        x = r.left() + pad
        if coming:
            draw_arrow(x, r.top() + 2)
            x += arrow + 4
        if text:
            p.setPen(QColor(theme.T["on_accent"]))
            p.drawText(QRectF(x, r.top(), tw + 1, h), Qt.AlignmentFlag.AlignCenter, text)
        p.end()

    def is_live(self) -> bool:
        return bool(self.rail.tabs.tabBar().property(f"_live{self.index}"))

    def _fill(self, r: QRectF, color: str, alpha: float):
        c = QColor(color)
        c.setAlphaF(alpha)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(r, 8, 8)


def set_tab_new(tabs: QTabWidget, index: int, on: bool):
    """Mark tab `index` on the rail with a small "New" pill (or take it off)."""
    tabs.tabBar().setProperty(f"_new{index}", bool(on))
    changed = getattr(tabs, "changed", None)
    if changed is not None:
        changed.emit()


def set_tab_count(tabs: QTabWidget, index: int, n: int, coming: bool = False, words: str = ""):
    """Show how many new things tab `index` has (0: none) and whether more are coming
    in; `words` says it to a screen reader."""
    bar = tabs.tabBar()
    if ([bar.property(f"_count{index}"), bar.property(f"_coming{index}")]
            == [n, coming] and bar.property(f"_countwords{index}") == words):
        return
    bar.setProperty(f"_count{index}", n)
    bar.setProperty(f"_coming{index}", coming)
    bar.setProperty(f"_countwords{index}", words)
    changed = getattr(tabs, "changed", None)
    if changed is not None:
        changed.emit()
