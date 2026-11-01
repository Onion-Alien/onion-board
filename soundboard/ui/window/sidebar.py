"""The main window's tabs as a thin rail down the left: one icon per tab, and a
button at the bottom that opens it out to show their names, with the onion and
the app's name and version on top. The foot is three zones with a thin line between:
what needs attention (not connected, an update: only when there is one),
what's on air (Live, who's listening, Stop all), then Settings with the open / shut
arrow beside it. The QTabWidget stays (its pages, live marks and settings
all work as before); only its bar is hidden, and the rail mirrors it: each tab's
icon (live badge, voice picture, warning tint), name, tip and whether it's shown.

Its parts: the sizes (railsizes.py), the tab buttons (railtabs.py), the On Air card
(onaircard.py) and the update card (updatecard.py)."""
from __future__ import annotations

import html
from collections.abc import Sequence

from PySide6.QtCore import QEvent, QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QBoxLayout, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QSpacerItem, QVBoxLayout, QWidget)

from soundboard.ui.kit import theme
from soundboard.i18n import _
from soundboard.ui.kit import icons
from soundboard.ui.kit.pixels import snap_to_pixels
from soundboard.ui.window.onaircard import OutputBlock
from soundboard.ui.window.railsizes import (BUTTON_W, COMPACT_H, FULL_W, ICON, ICON_PAD, LIVE_BAR_W,
                                            LOGO, OPEN_W, SHUT_W, SIDE_OPEN, SIDE_SHUT, SNAP_W,
                                            TEXT_W)
from soundboard.ui.window.railtabs import RailTab, SideTabs
from soundboard.ui.window.updatecard import UpdateCard


def put(w: QPushButton, text: str, full: str = "", tip: str = ""):
    """What a status button on the rail (`status`: Live, Stop all, the setup pill…)
    says. Expanded rails show its label; collapsed rails show its icon. `full`
    (default `text`) is its name for a screen reader and the first line of its tip,
    over `tip`. The same words again change nothing (the rail isn't laid out again)."""
    w.setProperty("railtext", text)
    w.setProperty("railfull", full or text)
    w.setProperty("railtip", tip)
    rail = w.parentWidget()
    while rail is not None and not isinstance(rail, SideRail):   # (in a see-through box)
        rail = rail.parentWidget()
    if rail is not None and w.property("railshown") != [text, full or text, tip]:
        rail.show_status(w)


class ClickLabel(QLabel):
    """A label that says when it's clicked (the version in the header)."""

    clicked = Signal()

    def __init__(self, text: str):
        super().__init__(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


class _Arrow(QPushButton):
    """The open / shut arrow; with property "dot" a small warning dot on its corner
    (an alert is waiting on the shut rail)."""

    def dot_rect(self) -> QRectF:
        """Beside the arrow's icon, wherever the button's edge is."""
        x = self.width() / 2 - (12 if self.isRightToLeft() else -4)
        return QRectF(x, (self.height() - ICON) / 2 - 4, 8, 8)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.property("dot"):
            p = QPainter(self)
            snap_to_pixels(p)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.T["warn_text"]))
            p.drawEllipse(self.dot_rect())
            p.end()


class ResizeHandle(QWidget):
    """Drag the inner edge between the rail's existing widths."""

    def __init__(self, rail):
        super().__init__(rail)
        self.rail = rail
        self.setObjectName("railslot")
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self._start = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.rail._squeezed:
            self._start = (event.globalPosition().x(), self.rail.width())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._start is not None:
            x, width = self._start
            delta = event.globalPosition().x() - x
            if self.rail.isRightToLeft():
                delta = -delta
            self.rail.drag_width(round(width + delta))
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._start is not None:
            self._start = None
            self.rail.finish_resize()
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class SideRail(QFrame):
    """The rail. `extras` (More tabs) sit under the tabs; at the bottom `alerts` (the
    setup pill, Offline, Update: shown only when needed), then `status` (Live, who's
    listening, Stop all: what used to be the window's header) in a column, with
    readable labels when open, then `foot` (Settings) with the open / shut button
    beside it (under it, shut). Extras show their "railtext" property as their words while open.
    `on_open(bool)` is called when the user opens or shuts it (to save it)."""

    orderChanged = Signal(list)

    def __init__(self, tabs: SideTabs, logo: QWidget, brand: QLabel, byline: QLabel,
                 extras: list[QPushButton], is_open: bool, foot: Sequence[QPushButton] = (),
                 on_open=None, status: Sequence[QPushButton] = (), order=(),
                 alerts: Sequence[QPushButton] = (), update: UpdateCard | None = None):
        super().__init__()
        self.setObjectName("sidebar")
        self.tabs = tabs
        self._open = is_open
        self._squeezed = False   # a narrow window: shut, whatever was picked
        self._compact = False    # a short window: the buttons closer together
        self._on_open = on_open
        self._drop_y = None
        self._drag_width = None
        # the key that jumps to tab index i, n-th shown on the rail, as its hover shows
        # it ("" = none); the window swaps in the tabs' own keys (TabControl.tab_key)
        self.key_for = lambda i, n: f"Ctrl+{n}" if n <= 9 else ""
        self.resize_handle = ResizeHandle(self)
        lay = self._lay = QVBoxLayout(self)
        lay.setSpacing(4)
        # the onion in the icons' column, open or shut, and when open the name and
        # "by Onion Alien" beside it (centred over the open rail, it sat off the column)
        self.logo = logo
        set_mark = getattr(logo, "set_mark", None)
        if set_mark is not None:
            set_mark(LOGO)
        head = QHBoxLayout()
        head.setSpacing(6)
        slot = QWidget()
        slot.setObjectName("railslot")   # see-through (theme.py): the onion's glow shows
        slot.setFixedWidth(BUTTON_W)
        sl = QHBoxLayout(slot)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(logo, 0, Qt.AlignmentFlag.AlignCenter)
        head.addWidget(slot, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.brand, self.byline = brand, byline
        words = QVBoxLayout()
        words.setSpacing(0)
        for w in (brand, byline):
            w.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            words.addWidget(w)
        byline.setWordWrap(True)
        brand.setWordWrap(True)   # (too narrow for one line: two, without the version)
        head.addLayout(words, 1)
        lay.addLayout(head)
        self._gaps = [self._gap(10)]   # (smaller in a short window: compact)
        self.buttons: list[RailTab] = []
        for i in range(tabs.count()):
            b = RailTab(self, i)
            b.installEventFilter(self)
            b.clicked.connect(lambda _c=False, i=i: (tabs.setCurrentIndex(i), self.sync()))
            lay.addWidget(b)
            self.buttons.append(b)
        self.set_order(order)
        self.extras = [*extras, *foot]
        self.foot = list(foot)   # (beside the arrow on the open rail)
        # a foot button showing its page in the tabs' place (Settings): it gets the
        # current tab's fill, and no tab has it
        self.foot_selected: QPushButton | None = None
        for w in self.foot:
            w.setCheckable(True)
            w.installEventFilter(self)
        for w in self.extras:   # the keyboard's ring, not one left by a click
            w.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._gaps.append(self._gap(10))   # More tabs isn't a tab
        for w in extras:
            lay.addWidget(w)
        lay.addStretch(1)
        # what was the window's header, there whatever tab you're on: icons only. In the
        # order they're drawn (the keyboard follows it): what needs attention first
        self.alerts = list(alerts)
        self.status = [*self.alerts, *status]
        self.output = None
        self._status_box = QBoxLayout(QBoxLayout.Direction.TopToBottom)
        self._status_box.setSpacing(4)
        self._status_pad_before = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum,
                                              QSizePolicy.Policy.Minimum)
        self._status_pad_after = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum,
                                             QSizePolicy.Policy.Minimum)
        self._status_box.addSpacerItem(self._status_pad_before)
        self.div_alerts = self._divider()   # under the alerts, only while there are any
        # the alerts, and who's listening, only on the open rail: shut, it keeps just
        # the few that matter (a dot on the arrow says an alert is waiting)
        self._open_only: list[QWidget] = []
        alert_wrap, alert_lay = self._wrap_lay()
        for w in self.status:
            w.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            w.setFixedWidth(BUTTON_W)
            if w in self.alerts:
                alert_lay.addWidget(w)
                w.installEventFilter(self)   # shown / hidden: the line and dot follow
            elif w.objectName() == "modebtn":
                wrap, lay = self._wrap_lay()
                lay.addWidget(w)
                self._status_box.addWidget(wrap)
            else:
                self._status_box.addWidget(w)
        if self.alerts:
            alert_lay.addWidget(self.div_alerts)
            self._status_box.insertWidget(1, alert_wrap)
        else:
            alert_wrap.deleteLater()
            self._open_only.remove(alert_wrap)
        power = next((w for w in self.status if w.objectName() == "onair"), None)
        connection = next((w for w in self.status if w.objectName() == "pill"), None)
        stop = next((w for w in self.status if w.objectName() == "danger"), None)
        if power is not None and connection is not None:
            self.output = OutputBlock(power, connection, stop)
            self._status_box.insertWidget(2 if self.alerts else 1, self.output)
            # 8 to Stop all under the open card, not the box's 4 (a spacer gets no
            # spacing of its own); refresh_output sizes it
            self._output_gap = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum,
                                           QSizePolicy.Policy.Fixed)
            self._status_box.insertItem(3 if self.alerts else 2, self._output_gap)
        # the update: over the On Air card, open or shut (a card open, a button shut),
        # 8 from the card under it as Stop all is (a spacer gets no spacing of its own)
        self.update_card = update
        if update is not None:
            update.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            at = (self._status_box.indexOf(self.output) if self.output
                  else self._status_box.count())
            self._status_box.insertWidget(at, update)
            self._update_gap = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum,
                                           QSizePolicy.Policy.Fixed)
            self._status_box.insertItem(at + 1, self._update_gap)
            update.installEventFilter(self)   # shown / hidden: its gap follows
        self._status_box.addSpacerItem(self._status_pad_after)   # (open: centered horizontally)
        lay.addLayout(self._status_box)
        self._gaps.append(self._gap(6))
        lay.addWidget(self._divider())
        self._gaps.append(self._gap(6))   # the same room under the line as over it
        # Settings and the open / shut arrow share a row when open, stack when shut
        self.toggle = _Arrow()
        self.toggle.setObjectName("railtoggle")
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.toggle.clicked.connect(lambda: self.set_open(not self._open))
        self.toggle.setFixedWidth(SHUT_W - 2 * SIDE_SHUT - 1)   # a tab button's, open too
        self._foot_box = QBoxLayout(QBoxLayout.Direction.TopToBottom)
        self._foot_box.setSpacing(4)
        # (mid: these take the spare room, so Settings and the arrow sit centred)
        self._foot_pads = [QSpacerItem(0, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
                           for _ in range(2)]
        self._foot_box.addSpacerItem(self._foot_pads[0])
        # Settings is its icon only (selected: the current tab's fill round it); open,
        # the arrow stays at the far side and a button between them sits in the middle
        self._foot_gaps = []
        for w in foot:
            self._foot_box.addWidget(w, 0)
            gap = QSpacerItem(0, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._foot_box.addSpacerItem(gap)
            self._foot_gaps.append(gap)
        self._foot_box.addWidget(self.toggle, 0)   # (mirrored: the right)
        self._foot_box.addSpacerItem(self._foot_pads[1])
        lay.addLayout(self._foot_box)
        tabs.changed.connect(self.sync)
        tabs.currentChanged.connect(self.sync)
        self._apply()

    def _wrap_lay(self) -> tuple[QWidget, QVBoxLayout]:
        """A see-through box for buttons that only the open rail shows, and its layout
        to put them in."""
        box = QWidget()
        box.setObjectName("railslot")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self._open_only.append(box)
        return box, lay

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setObjectName("raildiv")   # a 1 px line in the rail's border colour (theme.py)
        line.setFixedHeight(1)
        return line

    def eventFilter(self, obj: QObject, e: QEvent) -> bool:
        if (isinstance(obj, RailTab)
                and e.type() in (QEvent.Type.Move, QEvent.Type.Resize,
                                 QEvent.Type.Show, QEvent.Type.Hide)):
            # The live stripe is painted outside the button. Qt only invalidates
            # the button's rectangles when it moves, leaving the old stripe behind.
            self.update()
        if e.type() in (QEvent.Type.Show, QEvent.Type.Hide) and obj in self.alerts:
            QTimer.singleShot(0, self, self._sync_divider)   # (not after the rail's gone)
        elif (e.type() in (QEvent.Type.Show, QEvent.Type.Hide)
              and obj is getattr(self, "update_card", None)):
            QTimer.singleShot(0, self, self._size_update)
        elif (e.type() == QEvent.Type.Paint and isinstance(obj, QPushButton)
              and obj in self.foot):
            # a square round the icon (the button is as tall as the others, so it sits
            # level with them): selected, the current tab's soft fill (RailTab); else
            # the hover fill; the keyboard's ring (theme.py leaves these to here)
            side = min(obj.width(), obj.height())
            r = QRectF((obj.width() - side) / 2, (obj.height() - side) / 2, side, side)
            r = r.adjusted(0.5, 0.5, -0.5, -0.5)
            fill = None
            if obj.isChecked():
                colour, alpha = theme.rail_tint()
                fill = QColor(colour)
                fill.setAlphaF(alpha)
            elif obj.underMouse():
                fill = QColor(theme.T["btn_hover"])
            ring = obj.hasFocus()
            if fill is not None or ring:
                p = QPainter(obj)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setPen(QPen(QColor(theme.T["accent"]), 1) if ring else Qt.PenStyle.NoPen)
                p.setBrush(fill if fill is not None else Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(r, 8, 8)
                p.end()
        return False

    def select_foot(self, w: QPushButton | None):
        """`w` (Settings) is showing in the tabs' place, or (None) the tabs are again."""
        self.foot_selected = w
        for f in self.foot:
            f.setChecked(f is w)
            f.update()
        self.sync()

    def _sync_divider(self):
        """The line under the alerts is there only while one of them is."""
        if not self.alerts:
            return
        waiting = [w for w in self.alerts if not w.isHidden()]
        self.div_alerts.setVisible(bool(waiting))
        # shut, the alerts are out of sight: a dot on the arrow, their names on hover
        # (not the setup one: its dot is on the On Air icon, which leads to Setup)
        if self.output:
            waiting = [w for w in waiting if w is not self.output.connection]
        dot = bool(waiting) and (not self.is_open() or self._mid())
        if self.toggle.property("dot") != dot:
            self.toggle.setProperty("dot", dot)
            self.toggle.update()
        names = [w.property("railfull") or "" for w in waiting]
        self.toggle.setToolTip("\n".join(names) if dot else "")

    def set_order(self, order):
        """Move the rail buttons, retaining the pages' fixed indexes everywhere else."""
        by_index = {b.index: b for b in self.buttons}
        indexes = list(dict.fromkeys(i for i in order if i in by_index))
        indexes.extend(i for i in by_index if i not in indexes)
        before = self.buttons[0].previousInFocusChain() if self.buttons else None
        after = self.buttons[-1].nextInFocusChain() if self.buttons else None
        for b in self.buttons:
            self._lay.removeWidget(b)
        self.buttons = [by_index[i] for i in indexes]
        for slot, b in enumerate(self.buttons, 2):
            self._lay.insertWidget(slot, b)
        if before not in self.buttons and after not in self.buttons:
            chain = [before, *self.buttons, after]
            for first, second in zip(chain, chain[1:]):
                if first is not None and second is not None:
                    QWidget.setTabOrder(first, second)

    def _move_target(self, button, pos):
        visible = [b for b in self.buttons if b.isVisible()]
        if len(visible) < 2 or button not in visible or not self.rect().contains(pos):
            return None
        others = [b for b in visible if b is not button]
        slot = sum(pos.y() > b.geometry().center().y() for b in others)
        y = (others[slot].geometry().top() - 2 if slot < len(others)
             else others[-1].geometry().bottom() + 2)
        return visible, others, slot, y

    def preview_move(self, button, pos):
        target = self._move_target(button, pos)
        self._drop_y = target[3] if target else None
        self.update()

    def finish_move(self, button, pos):
        target = self._move_target(button, pos)
        self._drop_y = None
        self.update()
        if target is None:
            return
        visible, others, slot, _y = target
        others.insert(slot, button)
        # Hidden tabs keep their slots when More tabs adds them later.
        replacements = iter(others)
        order = [next(replacements).index if b in visible else b.index for b in self.buttons]
        if order != [b.index for b in self.buttons]:
            self.set_order(order)
            self.orderChanged.emit(order)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.LayoutDirectionChange and hasattr(self, "toggle"):
            self._apply()

    def paintEvent(self, e):
        """A live tab's mark (Settings > Live tabs, "tint"): a bar on the rail's edge
        beside it, in the highlight colour, with its icon in that colour too. A wash
        like the old tab bar's looked just like the current tab's fill."""
        super().paintEvent(e)
        if self._drop_y is not None:
            p = QPainter(self)
            snap_to_pixels(p)
            p.setPen(QPen(QColor(theme.T["accent"]), 2))
            p.drawLine(SIDE_OPEN, self._drop_y, self.width() - SIDE_OPEN, self._drop_y)
            p.end()
        if not self.tabs.property("_live_tint"):
            return   # the dot: in the icon itself (livedot / icons.set_tab_icon)
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.T["live_text"]))
        for b in self.buttons:
            if b.isVisible() and b.is_live():
                g = b.geometry()
                h = g.height() * 0.6
                # on the window's edge: the right one when mirrored (Arabic)
                x = self.width() - LIVE_BAR_W if self.isRightToLeft() else -LIVE_BAR_W
                r = QRectF(x, g.center().y() - h / 2, 2 * LIVE_BAR_W, h)
                p.drawRoundedRect(r, LIVE_BAR_W, LIVE_BAR_W)   # (half of it off the edge)

    # ---- the tab widget's state, on the rail
    def sync(self, *_a):
        bar = self.tabs.tabBar()
        cur = self.tabs.currentIndex()
        shown = self.is_open()
        shown_idx = {b: n for n, b in enumerate(
            (b for b in self.buttons if b.index < self.tabs.count()
             and self.tabs.isTabVisible(b.index)), 1)}
        for b in self.buttons:
            i = b.index
            if i >= self.tabs.count():
                b.hide()
                continue
            name = self.tabs.tabText(i).replace("&&", "&")
            tip = self.tabs.tabToolTip(i)
            b.setVisible(self.tabs.isTabVisible(i))
            b.setIcon(bar.tabIcon(i))
            b.setText(self._fit(b, name) if shown else "")
            b.setAccessibleName(name)
            # open: the name is on the button, no tip. Shut, it's all there is: the name
            # and the key that jumps to it. (A live tab's "● ON" line is for a screen reader.)
            n = shown_idx.get(b)
            key = "" if n is None else self.key_for(i, n)
            b.setToolTip("" if shown or not key else f"{name}  ({key})")
            # ("3 new sounds": the count on it, newsounds.py)
            b.setAccessibleDescription("\n".join(filter(None, (
                bar.property(f"_countwords{i}") or "", tip))))
            b.setChecked(i == cur and self.foot_selected is None)
            b.update()
        self.update()   # the live bars

    def _fit(self, w: QWidget, text: str) -> str:
        """`text` cut with "…" to what fits beside the icon on the open rail (a long
        translation pushed past the rail's edge; dragged narrower, less fits)."""
        room = TEXT_W - (OPEN_W - self._target_width())
        return ICON_PAD + w.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight,
                                                     max(0, room))

    def _label(self, w: QPushButton, name: str, tip: str, shown: bool):
        """A button under the tabs: its name while open and help for screen readers."""
        text = self._fit(w, name) if shown else ""
        w.setText(text)
        w.setAccessibleName(name)
        w.setAccessibleDescription(tip)
        w.setToolTip("")

    def show_status(self, w: QPushButton):
        """A status button as `put` left it, for the rail open or shut."""
        full, tip = w.property("railfull") or "", w.property("railtip") or ""
        text = w.property("railtext") or full
        w.setProperty("railshown", [w.property("railtext"), full, w.property("railtip")])
        if w.objectName() == "modebtn":
            text = _("Listening: {mode}", mode=text)
        w.setText(self._fit(w, text) if self.is_open() and not self._small(w) else "")
        w.setAccessibleName(full)
        if "<br>" in tip:   # rich text (Who's listening's tip)
            w.setToolTip(f"{html.escape(full)}<br>{tip}")
        else:
            w.setToolTip("\n".join(filter(None, (full, tip if tip != full else ""))))
        if self.output and w in (self.output.power, self.output.connection):
            self.refresh_output()   # (new status words can change the card's scale)

    # ---- open / shut
    def is_open(self) -> bool:
        # dragged: the shut column until the whole open layout fits (no half-way look)
        opened = (self._drag_width >= self._full_fit() if self._drag_width is not None
                  else self._open)
        return opened and not self._squeezed

    def _target_width(self) -> int:
        """The rail's width as set (width() lags until the layout runs)."""
        if self._drag_width is not None:
            return self._drag_width
        return OPEN_W if self.is_open() else SHUT_W

    def _inner_width(self) -> int:
        """A control's width under the tabs: the open rail's, or one button's."""
        return self._target_width() - 2 * SIDE_OPEN - 1 if self.is_open() else BUTTON_W

    def _brand_width(self) -> int:
        font = QFont(self.brand.font())
        font.setPointSizeF(12)   # the wordmark's size (theme.py)
        return QFontMetrics(font).horizontalAdvance(self.brand.text())

    def _brand_fits(self) -> bool:
        """The name on one line beside the onion, so the version fits under it (else
        the name takes both lines: the header is the same height either way)."""
        return self._target_width() - 2 * SIDE_OPEN - 1 - BUTTON_W - 6 >= self._brand_width()

    def _full_fit(self) -> int:
        """The narrowest open rail where the full layout fits (from 80% open): the
        name on one line, the output card with every line on one line, as small as it
        scales (a longer translation needs more room)."""
        side = 2 * SIDE_OPEN + 1
        need = [FULL_W, SHUT_W + round(0.8 * (OPEN_W - SHUT_W)),   # (from 80% open)
                side + BUTTON_W + 6 + self._brand_width()]   # the name on one line
        if self.output:
            # the card with every line on one line, scaled down as far as it goes
            # (never wrapped: the small card until then)
            need.append(side + self.output.need(self.output.MIN_SCALE))
        return max(FULL_W, min(OPEN_W, max(need)))

    def _small(self, w: QWidget) -> bool:
        """The output's help button keeps its shut size on the mid layout (the small
        output card's, until the full card fits)."""
        return bool(self.output) and w is self.output.connection and self._mid()

    def _mid(self) -> bool:
        """Open but short of _full_fit: the output card its small shut one, Settings
        just its icon, everything under the tabs centred."""
        return self.is_open() and self._target_width() < self._full_fit()

    def drag_width(self, width: int):
        before = self.is_open()
        self._drag_width = OPEN_W if width >= SNAP_W else max(SHUT_W, width)
        if before or self.is_open():
            self._apply()   # open: everything fits the new width
        else:   # shut: the column re-centres
            self.setFixedWidth(self._drag_width)
            self._size_lower_controls()

    def _place_column(self):
        """Shut, everything is one button wide, centred in the rail at any width
        (dragging it wider moves the whole column together); open, the side margins."""
        edge = 4 if self._compact else 10
        if self.is_open():
            left = right = SIDE_OPEN
        else:
            room = self._target_width() - 1 - BUTTON_W   # (its 1 px edge)
            left = room // 2
            right = room - left
        self._lay.setContentsMargins(left, edge, right, edge)

    def _size_lower_controls(self):
        width = self._inner_width()
        # mid: everything under the tabs centred, as on the shut rail (the small output
        # card, Stop all as wide as its name, Settings' icon and the arrow side by side)
        # until the full layout fits
        mid = self._mid()
        middle = Qt.AlignmentFlag.AlignHCenter if mid else Qt.AlignmentFlag.AlignLeading
        for widget in self.status:
            if self._small(widget):
                widget.setFixedWidth(BUTTON_W)
            else:
                widget.setFixedWidth(min(width, widget.sizeHint().width()) if mid else width)
            self._status_box.setAlignment(widget, middle)
        if self.output:
            self.output.setFixedWidth(BUTTON_W if mid else width)
            self._status_box.setAlignment(self.output, middle)
        self._size_update()
        # (split by hand, rounded as the centred toggle above: Qt's stretch gave the
        # odd pixel to the other side, so the pair wobbled 1 px against it while dragged)
        row = len(self.foot) + 1   # the foot buttons and the arrow
        # open, they're one row; dragged too narrow for that row, a column as when shut
        # (side by side, they ran into each other)
        side = self.is_open() and width >= row * BUTTON_W + (row - 1) * 4
        self._foot_box.setDirection(QBoxLayout.Direction.LeftToRight if side
                                    else QBoxLayout.Direction.TopToBottom)
        wide = side and not mid
        self._foot_box.setSpacing(0 if wide else 4)   # (wide: the gaps are the spacing)
        spare = max(0, width - row * BUTTON_W - (row - 1) * 4) if mid and side else 0
        pads = (spare // 2, spare - spare // 2)
        # open: Settings at the near side, the arrow at the far one and what's between
        # them exactly in the middle, so the gaps are split by hand too (Qt's stretch
        # gave the odd pixel to one gap); the odd pixel goes past the arrow instead,
        # so the middle one is on the cards' centre line
        gap_w = 0
        if wide:
            free = max(0, width - row * BUTTON_W)
            gap_w = free // max(1, len(self._foot_gaps))
            pads = (0, free - gap_w * len(self._foot_gaps))
        for pad, room in zip(self._foot_pads, pads):
            pad.changeSize(room, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        if wide:   # (and any pixel the layout has over the cards' width)
            self._foot_pads[1].changeSize(pads[1], 0, QSizePolicy.Policy.Expanding,
                                          QSizePolicy.Policy.Minimum)
        for widget in self.foot:
            widget.setFixedWidth(BUTTON_W)   # (its fill, hover and ring: a square, painted)
        # stacked on the open rail: centred, as everything else is there (shut, the
        # column's margins centre it)
        across = (Qt.AlignmentFlag.AlignHCenter if self.is_open() and not side
                  else Qt.AlignmentFlag(0))
        for widget in (*self.foot, self.toggle):
            self._foot_box.setAlignment(widget, across)
        for gap in self._foot_gaps:
            gap.changeSize(gap_w, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._foot_box.invalidate()
        self.toggle.setFixedWidth(BUTTON_W)
        self._place_column()

    def _size_update(self):
        """The update: the open rail's card, as wide as the On Air card and as tall as
        its words; shut and mid, one rail button in the column (centred, as the
        buttons round it are)."""
        card = getattr(self, "update_card", None)
        if card is None:
            return
        full = self.is_open() and not self._mid()
        card.set_card(full)
        if full:
            width = self._inner_width()
            card.setFixedWidth(width)
            card.setFixedHeight(card.height_for(width))
        else:
            card.setFixedSize(BUTTON_W, getattr(self, "_button_h", BUTTON_W))
        self._status_box.setAlignment(card, Qt.AlignmentFlag.AlignHCenter if self._mid()
                                      else Qt.AlignmentFlag.AlignLeading)
        shown = not card.isHidden()
        self._update_gap.changeSize(0, 4 if shown and full else 0,
                                    QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self._status_box.invalidate()

    def finish_resize(self):
        if self._drag_width is None:
            return
        opened = self._drag_width >= SNAP_W
        self._drag_width = None
        if opened != self._open:
            self.set_open(opened)
        else:
            self._apply()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_resize_handle()

    def _place_resize_handle(self):
        if hasattr(self, "resize_handle"):
            edge = 0 if self.isRightToLeft() else self.width() - 6
            self.resize_handle.setGeometry(edge, 0, 6, self.height())
            self.resize_handle.raise_()

    def set_open(self, on: bool):
        if on == self._open:
            return
        self._open = on
        self._apply()
        if self._on_open:
            self._on_open(on)

    def squeeze(self, tight: bool):
        """A narrow window shuts it (a responsive step); it opens again with room."""
        if tight != self._squeezed:
            self._squeezed = tight
            self._apply()

    def _gap(self, h: int):
        gap = QSpacerItem(0, h, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self._lay.addSpacerItem(gap)
        return gap, h

    def compact(self, tight: bool):
        """A short window packs the buttons closer (a responsive step), before the
        window gives up and turns into the mini player."""
        short = tight and self.window().height() < 520
        if tight != self._compact or short != getattr(self, "_short", None):
            self._compact = tight
            self._short = short
            self._apply()

    def _apply(self):
        shown = self.is_open()
        if self.property("rtl") != self.isRightToLeft():   # its border on the inner edge
            self.setProperty("rtl", self.isRightToLeft())
            self.style().unpolish(self)
            self.style().polish(self)
        self.setFixedWidth(self._drag_width if self._drag_width is not None
                           else OPEN_W if shown else SHUT_W)
        self._place_column()
        for gap, h in self._gaps:
            gap.changeSize(0, 2 if self._compact else h)
        self._lay.invalidate()
        mid = self._mid()
        self.brand.setVisible(shown)
        fits = not mid or self._brand_fits()   # (full: as it always was)
        self.byline.setVisible(shown and fits)
        if self.property("twolinebrand") != (not fits):   # two lines: a size smaller
            self.setProperty("twolinebrand", not fits)
            self.brand.style().unpolish(self.brand)
            self.brand.style().polish(self.brand)
        style = (Qt.ToolButtonStyle.ToolButtonTextBesideIcon if shown
                 else Qt.ToolButtonStyle.ToolButtonIconOnly)
        for b in self.buttons:
            b.setToolButtonStyle(style)
            b.setProperty("open", shown)
        for w in self.extras:
            if w.property("railtip") is None:   # its own tip, kept under the name
                w.setProperty("railtip", w.toolTip())
            name = w.property("railtext") or ""
            if w in self.foot:   # its icon only, open or shut (its name: screen readers)
                w.setProperty("railopen", False)
                self._label(w, name, w.property("railtip"), False)
            else:
                w.setProperty("railopen", shown)
                self._label(w, name, w.property("railtip"), shown)
            w.style().unpolish(w)
            w.style().polish(w)
        self._status_box.setDirection(QBoxLayout.Direction.TopToBottom)
        pad_h = QSizePolicy.Policy.Minimum
        self._status_pad_before.changeSize(0, 0, pad_h, QSizePolicy.Policy.Minimum)
        self._status_pad_after.changeSize(0, 0, pad_h, QSizePolicy.Policy.Minimum)
        self._status_box.invalidate()
        for w in self.status:
            w.setFixedWidth(BUTTON_W if self._small(w) else self._inner_width())
            w.setProperty("railopen", shown and not self._small(w))
            self.show_status(w)
            w.style().unpolish(w)
            w.style().polish(w)
        self._foot_box.setDirection(QBoxLayout.Direction.LeftToRight if shown
                                    else QBoxLayout.Direction.TopToBottom)
        for box in self._open_only:
            box.setVisible(shown and not mid)   # mid: as shut, the dot on the arrow
        self.toggle.setVisible(not self._squeezed)
        # a window with its side bar, the chevron pointing the way the rail will go:
        # mirrored (Arabic), the bar is on the right and it opens leftwards
        icons.set_icon(self.toggle, ("panel_close" if shown else "panel_open")
                       + ("_rtl" if self.isRightToLeft() else ""), size=ICON)
        # only the arrow, open or shut ("Hide tab names" was cut short in most
        # languages); its name is what it does now, on hover and for a screen reader
        self._label(self.toggle, _("Hide tab names") if shown else _("Show tab names"), "",
                    False)
        self.toggle.setProperty("railopen", shown)
        self.toggle.style().unpolish(self.toggle)
        self.toggle.style().polish(self.toggle)
        self._sync_divider()   # (the arrow's tip: _label cleared it)
        self.sync()
        # one height for everything on the rail: the buttons under the tabs came out
        # 3 px shorter, so their focus ring and hover box didn't match the tabs'
        everything = [*self.buttons, *self.status, *self.extras, self.toggle]
        for w in everything:
            w.setMinimumHeight(0)
            w.setMaximumHeight(16777215)
        short = self._compact and self.window().height() < 520
        h = COMPACT_H if short else max(34, *(w.sizeHint().height() for w in everything))
        self._button_h = h   # (the update's height, shut: _size_update)
        self._lay.setSpacing(1 if short else 4)
        if self.property("compact") != self._compact:   # less padding: the icons stay whole
            self.setProperty("compact", self._compact)
            for w in everything:
                w.style().unpolish(w)
                w.style().polish(w)
        for w in everything:
            w.setFixedHeight(h)
        self.refresh_output()
        self._place_resize_handle()
        self.updateGeometry()

    def refresh_output(self):
        if self.output:
            shown = self.is_open() and not self._mid()   # mid: the small one, in the column
            self.output.tight = self._compact
            self.output.refresh()   # (its status words first: the scale fits them)
            # narrower than it fits at full size: the same card, smaller
            self.output.set_scale((self.output.scale_for(self._inner_width()) or 1.0)
                                  if shown else 1.0)
            self.output.set_expanded(shown)
            # (the card last, Stop all in it: the room Stop all's row had under it)
            gap = 10 if self.output.rail_stop is not None else 8
            self._output_gap.changeSize(0, gap if shown else 0, QSizePolicy.Policy.Minimum,
                                        QSizePolicy.Policy.Fixed)
            self._status_box.invalidate()
            self.output.power.hide()
            if self.output.rail_stop is not None:   # open: Stop all is in the card
                self.output.rail_stop.setVisible(not shown)
            self.output.connection.setVisible(
                not shown and not bool(self.output.connection.property("outputgood")))
            self.output.refresh()
            self._sync_divider()
        self._size_lower_controls()
