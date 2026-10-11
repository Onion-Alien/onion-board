"""The main window's tabs as a thin rail down the left: one icon per tab, and a
button at the bottom that opens it out to show their names, with the onion and
the app's name and version on top. The foot is three zones with a thin line between:
what needs attention (not connected, offline, an update: only when there is one),
what's on air (Live, who's listening, Stop all), then Settings with the open / shut
arrow beside it. The QTabWidget stays (its pages, live marks and settings
all work as before); only its bar is hidden, and the rail mirrors it: each tab's
icon (live badge, voice picture, warning tint), name, tip and whether it's shown."""
from __future__ import annotations

import html

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QBoxLayout, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QSpacerItem, QTabWidget, QToolButton,
                               QVBoxLayout, QWidget)

from soundboard import theme
from soundboard.i18n import _
from soundboard.ui import icons

ICON = 20          # a tab's icon on the rail
SHUT_W = 43        # the rail's width, shut: its 1 px edge, 4, a 34 px button, 4...
OPEN_W = 190       # room for the brand and expanded listening status
FULL_W = (SHUT_W + OPEN_W) // 2   # dragged at least halfway, open (let go there, it
                   # snaps open): the mid layout until everything fits (_full_fit), then
                   # the full one. Short of halfway, the shut one, its icon column centred
LOGO = 24          # the onion: with its 5 px glow room, a tab button's width (BUTTON_W)
BUTTON_W = 34      # a button on the shut rail; open, its icon stays in this column
COMPACT_H = 28     # only genuinely short windows use smaller targets
SIDE_SHUT = 4      # the rail's own side margins, shut (a 34 px button)...
SIDE_OPEN = 10     # ...and open
LIVE_BAR_W = 3     # a live tab's bar on the rail's outer edge (Settings > Live tabs: tint)
ICON_PAD = " "   # Qt puts only ~4 px between a button's icon and its words, and with a
                      # style sheet on, no style or QSS rule can change that: an en space
                      # (~6 px) in front of the words does
TEXT_W = OPEN_W - 2 * SIDE_OPEN - ICON - 24   # a name's room on the open rail (icon,
                                              # padding, border, the gap after the icon)
TINT_ALPHA = 0.16  # the current tab's soft accent fill (an outlined box looked heavy)


class SideTabs(QTabWidget):
    """A QTabWidget whose bar is never shown (the rail stands in for it), and that
    says when anything the rail shows has changed."""

    changed = Signal()

    def __init__(self):
        super().__init__()
        self.tabBar().hide()
        self.tabBar().installEventFilter(self)
        # the hidden bar was the Tab key's stop after the rail: it can't take focus, so
        # Tab stuck on the rail's last button and never reached the page
        self.setFocusProxy(None)
        self.setFocusPolicy(Qt.NoFocus)
        self.tabBar().setFocusPolicy(Qt.NoFocus)

    def eventFilter(self, obj: QObject, e: QEvent) -> bool:
        if obj is self.tabBar() and e.type() == QEvent.Show:
            obj.hide()   # QTabWidget shows it again when it lays itself out
        return False

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
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(ICON, ICON))
        self.setFocusPolicy(Qt.TabFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setContextMenuPolicy(Qt.CustomContextMenu)

    def paintEvent(self, e):
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.isChecked():   # the current tab: a soft accent fill under the icon
            self._fill(r, theme.T["accent"], TINT_ALPHA)
        super().paintEvent(e)
        if self.hasFocus() and self._kbd_focus:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(QPen(QColor(theme.T["accent"]), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, 8, 8)

    def focusInEvent(self, e):
        # Qt also focuses the first tab on startup: that isn't keyboard navigation.
        self._kbd_focus = e.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason,
                                        Qt.ShortcutFocusReason)
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e):
        self._kbd_focus = False
        super().focusOutEvent(e)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press_pos = e.globalPosition().toPoint()
            self._dragging = False
        # TabFocus keeps the old tab focused after clicking another one.
        for b in self.rail.buttons:
            b._kbd_focus = False
            b.update()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press_pos is not None and e.buttons() & Qt.LeftButton:
            pos = e.globalPosition().toPoint()
            if (pos - self._press_pos).manhattanLength() >= QApplication.startDragDistance():
                self._dragging = True
                self.setDown(False)
                self.setCursor(Qt.ClosedHandCursor)
            if self._dragging:
                self.rail.preview_move(self, self.rail.mapFromGlobal(pos))
                e.accept()
                return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            dragging = self._dragging
            self._press_pos = None
            self._dragging = False
            self.setCursor(Qt.PointingHandCursor)
            if dragging:
                self.setDown(False)
                self.rail.finish_move(self, self.rail.mapFromGlobal(e.globalPosition().toPoint()))
                e.accept()
                return
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        """Up / down: the tab before / after it, as the arrows did on the old top bar
        (left / right too; mirrored, left is the next one)."""
        step = {Qt.Key_Up: -1, Qt.Key_Down: 1, Qt.Key_Left: -1, Qt.Key_Right: 1}.get(e.key())
        if step is None or e.modifiers() & ~Qt.KeypadModifier:
            return super().keyPressEvent(e)
        if self.isRightToLeft() and e.key() in (Qt.Key_Left, Qt.Key_Right):
            step = -step
        shown = [b for b in self.rail.buttons if b.isVisible()]
        if self in shown:
            b = shown[(shown.index(self) + step) % len(shown)]
            b.setFocus(Qt.TabFocusReason)
            b.click()

    def is_live(self) -> bool:
        return bool(self.rail.tabs.tabBar().property(f"_live{self.index}"))

    def _fill(self, r: QRectF, color: str, alpha: float):
        c = QColor(color)
        c.setAlphaF(alpha)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(r, 8, 8)


def put(w: QPushButton, text: str, full: str = "", tip: str = ""):
    """What a status button on the rail (`status`: Live, Stop all, the setup pill…)
    says. Expanded rails show its label; collapsed rails show its icon. `full`
    (default `text`) is its name for a screen reader and the first line of its tip,
    over `tip`."""
    w.setProperty("railtext", text)
    w.setProperty("railfull", full or text)
    w.setProperty("railtip", tip)
    rail = w.parentWidget()
    while rail is not None and not isinstance(rail, SideRail):   # (in a see-through box)
        rail = rail.parentWidget()
    if rail is not None:
        rail.show_status(w)


class OutputBlock(QFrame):
    """Named output switch and connection help for the expanded rail."""

    def __init__(self, power: QPushButton, connection: QPushButton):
        super().__init__()
        from soundboard.ui.voicepanel import Switch

        self.setObjectName("railoutput")
        self.power, self.connection = power, connection
        box = self.box = QVBoxLayout(self)
        box.setContentsMargins(8, 8, 8, 8)
        box.setSpacing(0)
        top = self.top = QHBoxLayout()
        top.setSpacing(4)
        mark = self.mark = QLabel()
        mark.setFixedSize(16, 20)
        mark.setContentsMargins(0, 4, 0, 0)   # optical centre of Segoe's visible glyphs
        mark.setAlignment(Qt.AlignCenter)
        icons.set_label_icon(mark, "live", "accent", size=16)
        self.title = QLabel(_("Sound output"))
        self.title.setObjectName("railoutputtitle")
        self.title.setWordWrap(True)
        self.title.setAlignment(Qt.AlignLeading | Qt.AlignVCenter)
        self.title.setMinimumWidth(0)
        self.switch = Switch()
        self.switch.setProperty("glyphoffset", 1)
        self.switch.setAccessibleName(_("Sound output"))
        self.title.setBuddy(self.switch)
        self.switch.setChecked(power.isChecked())
        self.switch.toggled.connect(power.setChecked)
        power.toggled.connect(self.switch.setChecked)
        top.addWidget(mark, 0, Qt.AlignVCenter)
        top.addWidget(self.title, 1)
        top.addWidget(self.switch)
        box.addLayout(top)
        self._status_gap = QSpacerItem(0, 4, QSizePolicy.Minimum, QSizePolicy.Fixed)
        box.addSpacerItem(self._status_gap)
        status = QHBoxLayout()
        status.setSpacing(6)
        self.status_icon = QLabel()
        self.status_icon.setFixedSize(16, 20)
        self.status_icon.setContentsMargins(0, 4, 0, 0)
        self.status_icon.setAlignment(Qt.AlignCenter)
        self.status_text = QLabel()
        self.status_text.setWordWrap(True)
        self.status_text.setAlignment(Qt.AlignLeading | Qt.AlignVCenter)
        self.status_text.setMinimumWidth(0)
        status.addWidget(self.status_icon, 0, Qt.AlignVCenter)
        status.addWidget(self.status_text, 1)
        box.addLayout(status)
        self.setup = QPushButton()
        self.setup.setObjectName("railoutputsetup")
        self.setup.setProperty("quiet", True)
        self.setup.setCursor(Qt.PointingHandCursor)
        self.setup.setMinimumHeight(34)
        self.setup.setAccessibleName(_("Set up output"))
        action = QHBoxLayout(self.setup)
        action.setContentsMargins(0, 4, 0, 4)
        action.setSpacing(4)
        label = QLabel(_("Set up output"))
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignLeading | Qt.AlignVCenter)
        label.setMinimumWidth(0)
        label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.arrow = QLabel()
        self.arrow.setFixedSize(16, 24)
        self.arrow.setContentsMargins(0, 2, 0, 0)
        self.arrow.setAlignment(Qt.AlignCenter)
        self.arrow.setAttribute(Qt.WA_TransparentForMouseEvents)
        action.addWidget(label, 0, Qt.AlignVCenter)
        action.addWidget(self.arrow, 0, Qt.AlignVCenter)
        action.addStretch(1)
        self.setup.clicked.connect(connection.click)
        box.addWidget(self.setup)
        self.refresh()

    def set_expanded(self, expanded: bool):
        self.setProperty("expanded", expanded)
        self.box.setContentsMargins(*(8, 8, 8, 8) if expanded else (0, 4, 0, 4))
        self.top.setDirection(QBoxLayout.LeftToRight if expanded else QBoxLayout.TopToBottom)
        self.title.setVisible(expanded)
        self.status_icon.setVisible(expanded)
        self.status_text.setVisible(expanded)
        self.setup.setVisible(expanded)
        self.switch.setFixedSize(38 if expanded else 34, 22)
        self._status_gap.changeSize(0, 4 if expanded else 0,
                                    QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.box.invalidate()
        self.top.setAlignment(self.mark, Qt.AlignVCenter if expanded else Qt.AlignHCenter)
        self.top.setAlignment(self.switch, Qt.AlignVCenter if expanded else Qt.AlignHCenter)
        self.setFixedWidth(OPEN_W - 2 * SIDE_OPEN - 1 if expanded else BUTTON_W)
        self.style().unpolish(self)
        self.style().polish(self)

    def refresh(self):
        self.switch.setToolTip(self.power.toolTip())
        self.switch.setAccessibleDescription(self.power.property("railfull") or "")
        self.status_text.setText(self.connection.property("railtext") or "")
        self.status_text.setToolTip(self.connection.property("railfull") or "")
        good = self.connection.property("state") == "ok"
        self.setup.setVisible(bool(self.property("expanded")) and not good)
        theme.set_tone(self.status_text, "ok" if good else "warn")
        self.status_icon.setPixmap(self.connection.icon().pixmap(16, 16))
        self.setup.setToolTip(self.connection.toolTip())
        icons.set_label_icon(self.arrow, "fold_back" if self.isRightToLeft() else "fold",
                             "accent", size=16)


class ClickLabel(QLabel):
    """A label that says when it's clicked (the version in the header)."""

    clicked = Signal()

    def __init__(self, text: str):
        super().__init__(text)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
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
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.T["warn_text"]))
            p.drawEllipse(self.dot_rect())
            p.end()


class ResizeHandle(QWidget):
    """Drag the inner edge between the rail's existing widths."""

    def __init__(self, rail):
        super().__init__(rail)
        self.rail = rail
        self.setObjectName("railslot")
        self.setCursor(Qt.SizeHorCursor)
        self._start = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self.rail._squeezed:
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
        if event.button() == Qt.LeftButton and self._start is not None:
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
                 extras: list[QPushButton], is_open: bool, foot: list[QPushButton] = (),
                 on_open=None, status: list[QPushButton] = (), order=(),
                 alerts: list[QPushButton] = ()):
        super().__init__()
        self.setObjectName("sidebar")
        self.tabs = tabs
        self._open = is_open
        self._squeezed = False   # a narrow window: shut, whatever was picked
        self._compact = False    # a short window: the buttons closer together
        self._on_open = on_open
        self._drop_y = None
        self._drag_width = None
        self.resize_handle = ResizeHandle(self)
        lay = self._lay = QVBoxLayout(self)
        lay.setSpacing(4)
        # the onion in the icons' column, open or shut, and when open the name and
        # "by Onion Alien" beside it (centred over the open rail, it sat off the column)
        self.logo = logo
        if hasattr(logo, "set_mark"):
            logo.set_mark(LOGO)
        head = QHBoxLayout()
        head.setSpacing(6)
        slot = QWidget()
        slot.setObjectName("railslot")   # see-through (theme.py): the onion's glow shows
        slot.setFixedWidth(BUTTON_W)
        sl = QHBoxLayout(slot)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(logo, 0, Qt.AlignCenter)
        head.addWidget(slot, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.brand, self.byline = brand, byline
        words = QVBoxLayout()
        words.setSpacing(0)
        for w in (brand, byline):
            w.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            words.addWidget(w)
        byline.setWordWrap(True)
        brand.setWordWrap(True)   # (the mid layout: two lines)
        head.addLayout(words, 1)
        lay.addLayout(head)
        self._gaps = [self._gap(10)]   # (smaller in a short window: compact)
        self.buttons: list[RailTab] = []
        for i in range(tabs.count()):
            b = RailTab(self, i)
            b.clicked.connect(lambda _c=False, i=i: (tabs.setCurrentIndex(i), self.sync()))
            lay.addWidget(b)
            self.buttons.append(b)
        self.set_order(order)
        self.extras = [*extras, *foot]
        self.foot = list(foot)   # (beside the arrow on the open rail)
        for w in self.extras:   # the keyboard's ring, not one left by a click
            w.setFocusPolicy(Qt.TabFocus)
        self._gaps.append(self._gap(10))   # More tabs isn't a tab
        for w in extras:
            lay.addWidget(w)
        lay.addStretch(1)
        # what was the window's header, there whatever tab you're on: icons only. In the
        # order they're drawn (the keyboard follows it): what needs attention first
        self.alerts = list(alerts)
        self.status = [*self.alerts, *status]
        self.output = None
        self._status_box = QBoxLayout(QBoxLayout.TopToBottom)
        self._status_box.setSpacing(4)
        self._status_pad_before = QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Minimum)
        self._status_pad_after = QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Minimum)
        self._status_box.addSpacerItem(self._status_pad_before)
        self.div_alerts = self._divider()   # under the alerts, only while there are any
        # the alerts, and who's listening, only on the open rail: shut, it keeps just
        # the few that matter (a dot on the arrow says an alert is waiting)
        self._open_only: list[QWidget] = []
        alert_wrap = self._wrap()
        for w in self.status:
            w.setFocusPolicy(Qt.TabFocus)
            w.setFixedWidth(BUTTON_W)
            if w in self.alerts:
                alert_wrap.layout().addWidget(w)
                w.installEventFilter(self)   # shown / hidden: the line and dot follow
            elif w.objectName() == "modebtn":
                wrap = self._wrap()
                wrap.layout().addWidget(w)
                self._status_box.addWidget(wrap)
            else:
                self._status_box.addWidget(w)
        if self.alerts:
            alert_wrap.layout().addWidget(self.div_alerts)
            self._status_box.insertWidget(1, alert_wrap)
        else:
            alert_wrap.deleteLater()
            self._open_only.remove(alert_wrap)
        power = next((w for w in self.status if w.objectName() == "onair"), None)
        connection = next((w for w in self.status if w.objectName() == "pill"), None)
        if power is not None and connection is not None:
            self.output = OutputBlock(power, connection)
            self._status_box.insertWidget(2 if self.alerts else 1, self.output)
        self._status_box.addSpacerItem(self._status_pad_after)   # (open: centered horizontally)
        lay.addLayout(self._status_box)
        self._gaps.append(self._gap(6))
        lay.addWidget(self._divider())
        # Settings and the open / shut arrow share a row when open, stack when shut
        self.toggle = _Arrow()
        self.toggle.setObjectName("railtoggle")
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.setFocusPolicy(Qt.TabFocus)
        self.toggle.clicked.connect(lambda: self.set_open(not self._open))
        self.toggle.setFixedWidth(SHUT_W - 2 * SIDE_SHUT - 1)   # a tab button's, open too
        self._foot_box = QBoxLayout(QBoxLayout.TopToBottom)
        self._foot_box.setSpacing(4)
        # (mid: these take the spare room, so Settings and the arrow sit centred)
        self._foot_pads = [QSpacerItem(0, 0, QSizePolicy.Fixed, QSizePolicy.Minimum)
                           for _ in range(2)]
        self._foot_box.addSpacerItem(self._foot_pads[0])
        for w in foot:
            self._foot_box.addWidget(w, 1)
        self._foot_box.addWidget(self.toggle, 0)   # (mirrored: the right)
        self._foot_box.addSpacerItem(self._foot_pads[1])
        lay.addLayout(self._foot_box)
        tabs.changed.connect(self.sync)
        tabs.currentChanged.connect(self.sync)
        self._apply()

    def _wrap(self) -> QWidget:
        """A see-through box for buttons that only the open rail shows."""
        box = QWidget()
        box.setObjectName("railslot")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self._open_only.append(box)
        return box

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setObjectName("raildiv")   # a 1 px line in the rail's border colour (theme.py)
        line.setFixedHeight(1)
        return line

    def eventFilter(self, obj: QObject, e: QEvent) -> bool:
        if e.type() in (QEvent.Show, QEvent.Hide) and obj in self.alerts:
            QTimer.singleShot(0, self, self._sync_divider)   # (not after the rail's gone)
        return False

    def _sync_divider(self):
        """The line under the alerts is there only while one of them is."""
        if not self.alerts:
            return
        waiting = [w for w in self.alerts if not w.isHidden()]
        self.div_alerts.setVisible(bool(waiting))
        # shut, the alerts are out of sight: a dot on the arrow, their names on hover
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
        if e.type() == QEvent.LayoutDirectionChange and hasattr(self, "toggle"):
            self._apply()

    def paintEvent(self, e):
        """A live tab's mark (Settings > Live tabs, "tint"): a bar on the rail's edge
        beside it, in the highlight colour, with its icon in that colour too. A wash
        like the old tab bar's looked just like the current tab's fill."""
        super().paintEvent(e)
        if self._drop_y is not None:
            p = QPainter(self)
            p.setPen(QPen(QColor(theme.T["accent"]), 2))
            p.drawLine(SIDE_OPEN, self._drop_y, self.width() - SIDE_OPEN, self._drop_y)
            p.end()
        if not self.tabs.property("_live_tint"):
            return   # the dot: in the icon itself (livedot / icons.set_tab_icon)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
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
            b.setToolTip("" if shown or n is None or n > 9 else f"{name}  (Ctrl+{n})")
            b.setAccessibleDescription(tip)
            b.setChecked(i == cur)
            b.update()
        self.update()   # the live bars

    def _fit(self, w: QWidget, text: str) -> str:
        """`text` cut with "…" to what fits beside the icon on the open rail (a long
        translation pushed past the rail's edge; dragged narrower, less fits)."""
        room = TEXT_W - (OPEN_W - self._target_width())
        return ICON_PAD + w.fontMetrics().elidedText(text, Qt.ElideRight, max(0, room))

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
        if w.objectName() == "modebtn":
            text = _("Listening: {mode}", mode=text)
        w.setText(self._fit(w, text) if self.is_open() and not self._small(w) else "")
        w.setAccessibleName(full)
        if "<br>" in tip:   # rich text (Who's listening's tip)
            w.setToolTip(f"{html.escape(full)}<br>{tip}")
        else:
            w.setToolTip("\n".join(filter(None, (full, tip if tip != full else ""))))
        if self.output and w in (self.output.power, self.output.connection):
            self.output.refresh()

    # ---- open / shut
    def is_open(self) -> bool:
        opened = self._drag_width >= FULL_W if self._drag_width is not None else self._open
        return opened and not self._squeezed

    def _target_width(self) -> int:
        """The rail's width as set (width() lags until the layout runs)."""
        if self._drag_width is not None:
            return self._drag_width
        return OPEN_W if self.is_open() else SHUT_W

    def _inner_width(self) -> int:
        """A control's width under the tabs: the open rail's, or one button's."""
        return self._target_width() - 2 * SIDE_OPEN - 1 if self.is_open() else BUTTON_W

    def _full_fit(self) -> int:
        """The narrowest open rail where the full layout fits, every word on its line:
        the name, "Sound output" beside its switch, Settings beside the arrow (a longer
        translation needs more room)."""
        side = 2 * SIDE_OPEN + 1
        font = QFont(self.brand.font())
        font.setPointSizeF(12)   # the wordmark's full size (theme.py)
        need = [side + BUTTON_W + 6 + QFontMetrics(font).horizontalAdvance(self.brand.text())]
        if self.output:
            title = self.output.title.fontMetrics().horizontalAdvance(_("Sound output"))
            need.append(side + 16 + 16 + 4 + title + 4 + 38 + 2)
        for w in self.foot:
            name = ICON_PAD + (w.property("railtext") or "")
            need.append(side + ICON + 24 + w.fontMetrics().horizontalAdvance(name)
                        + 4 + BUTTON_W)
        return max(FULL_W, min(OPEN_W, max(need)))

    def _small(self, w: QWidget) -> bool:
        """The output's help button keeps its shut size on the mid layout (the small
        output card's, until the full card fits)."""
        return bool(self.output) and w is self.output.connection and self._mid()

    def _mid(self) -> bool:
        """Open but short of _full_fit: the name smaller on two lines without the
        version, the output card its small shut one, Settings just its icon."""
        return self.is_open() and self._target_width() < self._full_fit()

    def drag_width(self, width: int):
        before = self.is_open()
        self._drag_width = max(SHUT_W, min(OPEN_W, width))
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
        middle = Qt.AlignHCenter if mid else Qt.AlignLeading
        for widget in self.status:
            if self._small(widget):
                widget.setFixedWidth(BUTTON_W)
            else:
                widget.setFixedWidth(min(width, widget.sizeHint().width()) if mid else width)
            self._status_box.setAlignment(widget, middle)
        if self.output:
            self.output.setFixedWidth(BUTTON_W if mid else width)
            self._status_box.setAlignment(self.output, middle)
        for pad in self._foot_pads:
            pad.changeSize(0, 0, QSizePolicy.Expanding if mid else QSizePolicy.Fixed,
                           QSizePolicy.Minimum)
        self._foot_box.invalidate()
        for widget in self.foot:
            widget.setMinimumWidth(BUTTON_W if mid else 0)
            widget.setMaximumWidth(BUTTON_W if mid else 16777215)
        self.toggle.setFixedWidth(BUTTON_W)
        self._place_column()

    def finish_resize(self):
        if self._drag_width is None:
            return
        opened = self._drag_width >= FULL_W
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
        gap = QSpacerItem(0, h, QSizePolicy.Minimum, QSizePolicy.Fixed)
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
        self.byline.setVisible(shown and not mid)
        if self.property("narrowbrand") != mid:
            self.setProperty("narrowbrand", mid)
            self.brand.style().unpolish(self.brand)
            self.brand.style().polish(self.brand)
        style = Qt.ToolButtonTextBesideIcon if shown else Qt.ToolButtonIconOnly
        for b in self.buttons:
            b.setToolButtonStyle(style)
            b.setProperty("open", shown)
        for w in self.extras:
            if w.property("railtip") is None:   # its own tip, kept under the name
                w.setProperty("railtip", w.toolTip())
            w.setProperty("railopen", shown)
            self._label(w, w.property("railtext") or "", w.property("railtip"),
                        shown and not (mid and w in self.foot))
            w.style().unpolish(w)
            w.style().polish(w)
        self._status_box.setDirection(QBoxLayout.TopToBottom)
        pad_h = QSizePolicy.Minimum
        self._status_pad_before.changeSize(0, 0, pad_h, QSizePolicy.Minimum)
        self._status_pad_after.changeSize(0, 0, pad_h, QSizePolicy.Minimum)
        self._status_box.invalidate()
        for w in self.status:
            w.setFixedWidth(BUTTON_W if self._small(w) else self._inner_width())
            w.setProperty("railopen", shown and not self._small(w))
            self.show_status(w)
            w.style().unpolish(w)
            w.style().polish(w)
        self._foot_box.setDirection(QBoxLayout.LeftToRight if shown else QBoxLayout.TopToBottom)
        for box in self._open_only:
            box.setVisible(shown and not mid)   # mid: as shut, the dot on the arrow
        self._sync_divider()
        self.toggle.setVisible(not self._squeezed)
        # the arrow points the way the rail will go: mirrored (Arabic), it opens leftwards
        icons.set_icon(self.toggle, "back" if shown != self.isRightToLeft() else "forward",
                       size=ICON)
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
            self.output.set_expanded(shown)
            self.output.power.hide()
            self.output.connection.setVisible(
                not shown and not bool(self.output.connection.property("outputgood")))
            self.output.refresh()
            self._sync_divider()
        self._size_lower_controls()
