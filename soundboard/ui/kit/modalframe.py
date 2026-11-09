"""The one look for pop-up cards and small modals (DESIGN.md *Standard kit*, *Modal frame*).

`ModalFrame` is the panel: a rounded, raised surface with a header (a small mascot, the
title, a one-line subtitle and a ✕), a body of short points that each have an icon, and a
footer with the card's one main button. Put it in any dialog. `InfoCard` is the ready-made
pop-up around it: frameless, on a soft shadow, it closes on Esc, the ✕, its button or a
click outside (that click goes no further), and gives the focus back to what opened it.

A dialog whose whole face is a ModalFrame (the frame is the first thing in its layout,
with no margins) becomes a card window too: no Windows title bar over the card's own
title and ✕, a soft shadow, dragged by the card's header. Its ✕ does what the window's
did (`close`).

Every card window is owned by the window it opens from, never by a widget inside a page
card: the style sheet's "inside a card" rules would reach into it and leave its panel
and buttons see-through.

Its look comes from the app style sheet (`#modalframe`, `#modalpointicon`, ...), so it
follows every theme; nothing here sets a colour or a font size.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFrame,
                               QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSizePolicy, QSpacerItem, QVBoxLayout, QWidget)
from shiboken6 import isValid as qt_valid

from soundboard.i18n import _
from soundboard.ui.kit import icons, theme
from soundboard.ui.kit.panel import icon_button

WIDTH = 480      # the panel's width (a pop-up card); dialogs stay <= 620 (DESIGN.md)
NARROWEST = 320  # a pop-up card's panel squeezed into a narrow window (InfoCard.place_at)
MASCOT = 56      # the mascot's height in the header
SHADOW = 20      # room each side of a card window's panel for its shadow
SHADOW_TOP = 14     # (less above: the shadow falls down)
SHADOW_BOTTOM = 26
BLUR, DROP = 24, 6   # the shadow's blur and how far down it falls: it fades out inside
                     # that room (a wider blur was cut off by the window's square edge)
BADGE = 32       # a point's icon square
GLYPH = 18       # the icon in it
GAP = 14         # between the icon column and the words
BODY_GAP = 18    # between the header and the body
DIALOG_W = 440   # a small modal's panel (confirm / ask_text / notice)
TONES = {"info": "accent_text", "warn": "warn_text", "error": "error_text"}


def owner(parent: QWidget | None) -> QWidget | None:
    """The window a card window opening from `parent` belongs to. Never a widget inside a
    page: the style sheet matches a window's parents too, so a card owned by something in
    a page card (`QFrame#card QWidget { background:transparent }`) lost its panel."""
    return parent.window() if parent is not None else None


def add_shadow(win: QWidget, frame: QWidget) -> QGraphicsDropShadowEffect:
    """`frame` on a soft shadow inside `win` (a see-through window): the room round it and
    the effect; `shadow_tone` sets its strength for the theme when it shows."""
    win.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    lay = win.layout()
    if lay is not None:
        lay.setContentsMargins(SHADOW, SHADOW_TOP, SHADOW, SHADOW_BOTTOM)
    effect = QGraphicsDropShadowEffect(frame)
    effect.setBlurRadius(BLUR)
    effect.setOffset(0, DROP)
    frame.setGraphicsEffect(effect)
    shadow_tone(effect)
    return effect


def shadow_tone(effect: QGraphicsDropShadowEffect) -> None:
    """The theme now: a dark theme needs a deeper shadow to show at all."""
    effect.setColor(QColor(0, 0, 0, 60 if theme.is_light() else 150))


class _CardWindow(QObject):
    """On a dialog made into a card window: its shadow follows the theme, and it gets the
    room for that shadow on top of the size its code gave it (that size was the card's)."""

    def __init__(self, dlg: QDialog, effect: QGraphicsDropShadowEffect):
        super().__init__(dlg)
        self.effect = effect
        self.grown = False
        dlg.installEventFilter(self)

    def eventFilter(self, obj, ev):   # noqa: N802 - Qt API
        if ev.type() == QEvent.Type.Show and isinstance(obj, QWidget):
            shadow_tone(self.effect)
            if not self.grown:
                self.grown = True
                self._grow(obj)
        return False

    def _grow(self, w: QWidget) -> None:
        dx, dy = 2 * SHADOW, SHADOW_TOP + SHADOW_BOTTOM
        big = 16777215   # (QWIDGETSIZE_MAX: no limit)
        if w.minimumWidth():   # (a width set for the card: GUIDE_W, 680 for two panes)
            w.setMinimumWidth(min(w.minimumWidth() + dx, big))
        if w.maximumWidth() < big:
            w.setMaximumWidth(w.maximumWidth() + dx)
        if w.maximumHeight() < big:
            w.setMaximumHeight(w.maximumHeight() + dy)
        lay = w.layout()
        if lay is not None:
            lay.activate()   # (its minimum now has the shadow's room in it)
        w.resize(max(w.width() + dx, w.minimumWidth()), max(w.height() + dy, w.minimumHeight()))
        if w.testAttribute(Qt.WidgetAttribute.WA_Moved):   # placed by its code: the card
            w.move(w.x() - SHADOW, w.y() - SHADOW_TOP)     # stays where it was put
        # (otherwise QDialog centres it on its window next, shadow and all: a move here
        # would stop that and leave it in the screen's corner)


def _is_face(frame: QWidget, dlg: QWidget) -> bool:
    """Is `frame`, just put in `dlg`, the dialog's whole face (a titled dialog, not made
    yet, whose layout has nothing else and no margins)?"""
    if not isinstance(dlg, QDialog) or not dlg.isWindow():
        return False
    if dlg.testAttribute(Qt.WidgetAttribute.WA_WState_Created) or dlg.property("native_title"):
        return False
    flags = dlg.windowFlags()
    if (flags & Qt.WindowType.FramelessWindowHint
            or (flags & Qt.WindowType.WindowType_Mask) != Qt.WindowType.Dialog):
        return False   # already a card (ModalDialog), or a pop-up / tool window
    lay = dlg.layout()
    if lay is None or lay.count():   # (the frame isn't in it yet: it's being added)
        return False
    m = lay.contentsMargins()
    return (m.left(), m.top(), m.right(), m.bottom()) == (0, 0, 0, 0)


def _make_card_window(frame: ModalFrame, dlg: QDialog) -> None:
    """`dlg`, whose face `frame` is, as a card window (see the module's docstring)."""
    flags = dlg.windowFlags() | Qt.WindowType.FramelessWindowHint
    above = dlg.parentWidget()
    if above is not None and not above.isWindow():
        dlg.setParent(owner(above), flags)   # (not made yet: nothing to rebuild)
    else:
        dlg.setWindowFlags(flags)
    frame.setProperty("docked", False)   # its own edge and corners now
    _CardWindow(dlg, add_shadow(dlg, frame))
    if frame.close_btn.isHidden():   # it relied on the window's ✕
        frame.close_btn.show()
        frame.close_btn.clicked.connect(dlg.close)


def mascot_pixmap(kind: str, height: int, dpr: float) -> QPixmap:
    """Bun ("bun") or Hoot ("owl", the Triggers tab's), `height` px tall, sharp at `dpr`."""
    if kind == "owl":
        from soundboard.style.owl import owl_image
        pm = QPixmap.fromImage(owl_image(round(height * dpr), look=0.0))
    else:
        from soundboard.ui.bun.bunny import bunny_pixmap
        pm = bunny_pixmap(height, dpr=dpr)
    pm.setDevicePixelRatio(dpr)
    return pm


class ModalPoint(QWidget):
    """One body point: an icon on a soft accent square, a bold line and an optional
    quieter line under it. `title` / `text` are the two labels."""

    def __init__(self, icon: str, title: str, text: str = "", *, rich: bool = False,
                 lead: int = BADGE, parent=None):
        super().__init__(parent)
        self.setObjectName("modalpoint")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(GAP)
        # the icon centred in a column `lead` wide (the mascot's), so the words start on
        # the title's line: one icon column, one text edge (DESIGN.md section 10)
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        self.icon = QLabel()
        self.icon.setObjectName("modalpointicon")
        self.icon.setFixedSize(BADGE, BADGE)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icons.set_label_icon(self.icon, icon, "accent_text", GLYPH)
        column.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addStretch(1)
        holder = QWidget()
        holder.setObjectName("modalpoint")
        holder.setFixedWidth(max(lead, BADGE))
        holder.setLayout(column)
        row.addWidget(holder)
        words = QVBoxLayout()
        words.setContentsMargins(0, 0, 0, 0)
        words.setSpacing(2)
        fmt = Qt.TextFormat.RichText if rich else Qt.TextFormat.PlainText
        self.title = QLabel(title)
        self.title.setObjectName("modalpointtitle")
        self.title.setTextFormat(fmt)
        self.title.setWordWrap(True)
        self.title.setMinimumWidth(1)   # (sized for its real width: see add_text)
        words.addWidget(self.title)
        self.text = QLabel(text)
        self.text.setObjectName("muted")
        self.text.setTextFormat(fmt)
        self.text.setWordWrap(True)
        self.text.setMinimumWidth(1)
        if not text:   # (never setVisible(True) here: with no parent yet it'd be a window)
            self.text.hide()
        words.addWidget(self.text)
        row.addLayout(words, 1)

    def sizeHint(self) -> QSize:   # noqa: N802 - Qt API
        s = super().sizeHint()
        return QSize(s.width(), max(s.height(), BADGE))


class ModalFrame(QFrame):
    """The panel of a pop-up card or small modal.

    `mascot`: "bun", "owl" or "" (none). `icon` + `tone` instead of a mascot: an icon in
    the header in the tone's colour ("info", "warn", "error": `notice`). `close`: show the
    ✕ (`close_btn`, wired by the owner). Parts: `heading` (QLabel#helptitle), `subtitle`
    (QLabel#muted, hidden when empty), `mascot`, `icon`, `close_btn`, `header` (the
    header's QHBoxLayout), `body` (a QVBoxLayout: add_point / add_text / add_widget fill
    it; a plain QWidget row put there yourself: name it "modalrow") and `footer` (a
    QHBoxLayout, shown once add_button has put a button in it). `docked`: the frame fills
    a whole titled dialog (no edge, no corners)."""

    def __init__(self, title: str, subtitle: str = "", *, mascot: str = "bun",
                 icon: str = "", tone: str = "info", close: bool = True,
                 docked: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("modalframe")
        self.setProperty("docked", docked)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 20, 20)   # 20 on the right: the ✕ sits in its corner
        v.setSpacing(0)

        header = self.header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(GAP)
        self.picture: QWidget | None = None   # set_picture's widget
        self.mascot: QLabel | None = None
        self.lead = BADGE   # the icon column's width: the mascot's, when there is one
        if mascot:
            self.mascot = QLabel()
            self.mascot.setObjectName("modalmascot")
            self.mascot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pm = mascot_pixmap(mascot, MASCOT, self.devicePixelRatioF() or 1.0)
            self.mascot.setPixmap(pm)
            self.lead = round(pm.width() / pm.devicePixelRatio())
            self.mascot.setFixedSize(self.lead, MASCOT)
            header.addWidget(self.mascot, 0, Qt.AlignmentFlag.AlignVCenter)
        self.icon: QLabel | None = None
        if icon and not mascot:
            self.icon = QLabel()
            self.icon.setObjectName("modalicon")
            self.icon.setFixedSize(BADGE, BADGE)
            self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icons.set_label_icon(self.icon, icon, TONES.get(tone, "accent_text"), 28)
            header.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        words = QVBoxLayout()
        words.setContentsMargins(0, 0, 0, 0)
        words.setSpacing(2)
        words.addStretch(1)
        self.heading = QLabel(title)
        self.heading.setObjectName("helptitle")
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        self.heading.setWordWrap(True)
        words.addWidget(self.heading)
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("muted")
        self.subtitle.setTextFormat(Qt.TextFormat.PlainText)
        self.subtitle.setWordWrap(True)
        if not subtitle:   # (hide only: shown with no parent yet it'd be a window of its own)
            self.subtitle.hide()
        words.addWidget(self.subtitle)
        words.addStretch(1)
        header.addLayout(words, 1)
        self.close_btn = icon_button("close", _("Close"), size=16)
        if not close:
            self.close_btn.hide()
        header.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(header)

        self._gap = QSpacerItem(0, BODY_GAP, QSizePolicy.Policy.Minimum,
                                QSizePolicy.Policy.Fixed)   # none when the body is empty
        v.addSpacerItem(self._gap)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 4, 0)   # (lines up with the ✕'s inner edge)
        self.body.setSpacing(14)
        v.addLayout(self.body)

        self._foot = QWidget()
        self._foot.setObjectName("modalfoot")
        self.footer = QHBoxLayout(self._foot)
        self.footer.setContentsMargins(0, 20, 4, 0)
        self.footer.setSpacing(8)
        self.footer.addStretch(1)
        self._lefts = 0   # buttons before the stretch (add_button(left=True))
        self._foot.hide()
        v.addWidget(self._foot)

    def event(self, ev):   # noqa: N802 - Qt API
        if ev.type() == QEvent.Type.ParentChange:
            dlg = self.parentWidget()
            if dlg is not None and _is_face(self, dlg):
                assert isinstance(dlg, QDialog)   # (_is_face checked)
                _make_card_window(self, dlg)
        return super().event(ev)

    def mousePressEvent(self, ev):   # noqa: N802 - Qt API
        # a card window has no title bar: it's dragged by its header (or any bare spot)
        win = self.window()
        handle = win.windowHandle()
        if (ev.button() == Qt.MouseButton.LeftButton and handle is not None
                and win.windowFlags() & Qt.WindowType.FramelessWindowHint
                and (win.windowFlags() & Qt.WindowType.WindowType_Mask)
                != Qt.WindowType.Popup):
            handle.startSystemMove()
            ev.accept()
            return
        super().mousePressEvent(ev)

    def _indent(self) -> int:
        """Where the body's words start: on the title's edge when a picture is beside it."""
        shown = (self.mascot, self.icon, self.picture)
        return self.lead + GAP if any(w is not None for w in shown) else 0

    def set_picture(self, w: QWidget) -> QWidget:
        """`w` in the header in place of the mascot or icon (a big emoji tile, a device
        picture). Call it before adding points or text: they line up with its width."""
        for old in (self.mascot, self.icon, self.picture):
            if old is not None:
                self.header.removeWidget(old)
                old.hide()
                old.deleteLater()
        self.mascot = self.icon = None
        self.picture = w
        self.lead = max(BADGE, w.minimumWidth() or w.sizeHint().width())
        self.header.insertWidget(0, w, 0, Qt.AlignmentFlag.AlignVCenter)
        return w

    def showEvent(self, ev):   # noqa: N802 - Qt API
        # no gap under the header when nothing is in the body (a question with no words)
        gap = 0 if self.body.isEmpty() else BODY_GAP
        if self._gap.sizeHint().height() != gap:
            self._gap.changeSize(0, gap, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            lay = self.layout()
            if lay is not None:
                lay.invalidate()
        super().showEvent(ev)

    def add_point(self, icon: str, title: str, text: str = "", *,
                  rich: bool = False) -> ModalPoint:
        """A point in the body: `icon` (a name in icons.SHAPES), a bold line, a quieter one."""
        p = ModalPoint(icon, title, text, rich=rich, lead=self.lead)
        self.body.addWidget(p)
        return p

    def add_text(self, text: str, *, rich: bool = False) -> QLabel:
        """A plain paragraph in the body (for a card with no points)."""
        lbl = QLabel(text)
        lbl.setObjectName("helpbody")
        lbl.setTextFormat(Qt.TextFormat.RichText if rich else Qt.TextFormat.PlainText)
        lbl.setWordWrap(True)
        # a wrapped label claims a minimum width wider than the card (624 px for a long
        # German text): the layout then sized it for that width and cut its last lines off
        lbl.setMinimumWidth(1)
        if rich:
            lbl.setOpenExternalLinks(True)
        row = QHBoxLayout()   # starts on the title's line, like the points' words
        row.setContentsMargins(self._indent(), 0, 0, 0)
        row.addWidget(lbl)
        self.body.addLayout(row)
        return lbl

    def add_widget(self, w: QWidget) -> QWidget:
        """Any other part of the body (a text box), on the title's edge like the words."""
        row = QHBoxLayout()
        row.setContentsMargins(self._indent(), 0, 0, 0)
        row.addWidget(w)
        grows = (QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding,
                 QSizePolicy.Policy.Ignored)
        if w.sizePolicy().horizontalPolicy() not in grows:
            row.addStretch(1)   # at its own width, on the left (a dropdown), not centred
        self.body.addLayout(row)
        return w

    def add_button(self, text: str, *, primary: bool = False, danger: bool = False,
                   left: bool = False) -> QPushButton:
        """A footer button, right-aligned, in the order added (the main one first: DESIGN.md
        *Dialog anatomy*). `primary`: the card's one filled button; `danger`: a verb that
        can't be undone (#danger); `left`: on the row's left end, before the gap (a side
        action: Release page, Show the report)."""
        b = QPushButton(text)
        if danger:   # (named before it's in a layout: once styled, a new name changes nothing)
            b.setObjectName("danger")
        elif primary:
            b.setObjectName("primary")
            b.setDefault(True)
        if left:
            self.footer.insertWidget(self._lefts, b)   # before the stretch
            self._lefts += 1
        else:
            self.footer.addWidget(b)
        self._foot.show()
        return b


class InfoCard(QDialog):
    """A pop-up card on the shared frame: explain something in 2-4 short points.

    `points`: (icon, title, text) tuples; `text`: a paragraph instead (or as well).
    `button`: the main button's words ("" for none). Parts: `frame` (the ModalFrame),
    `heading`, `subtitle`, `mascot`, `close_btn`, `ok_btn`, `points` and `body` (the
    paragraph's QLabel, hidden when there's no `text`). The caller places it (`move`)
    and opens it."""

    def __init__(self, title: str, subtitle: str = "", *, mascot: str = "bun",
                 points=(), text: str = "", rich: bool = False, button: str | None = None,
                 width: int = WIDTH, parent=None):
        # (no Windows shadow: it's square, round the whole window, past the panel's corners)
        super().__init__(owner(parent), Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        # a click outside only closes it: Qt would hand that click on to what's under it
        # (it picked the voice tile under the Effects card, and undid what was just added)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        self._opener = QApplication.focusWidget()
        self.setWindowTitle(title)
        self.setAccessibleName(title)
        room = self.screen().availableGeometry().width() - 24
        self.setFixedWidth(min(width + 2 * SHADOW, room))
        outer = QVBoxLayout(self)
        self.frame = ModalFrame(title, subtitle, mascot=mascot)
        outer.addWidget(self.frame)
        self._shadow = add_shadow(self, self.frame)
        self.heading = self.frame.heading
        self.subtitle = self.frame.subtitle
        self.mascot = self.frame.mascot
        self.close_btn = self.frame.close_btn
        self.close_btn.clicked.connect(self.reject)
        self.points = [self.frame.add_point(*p, rich=rich) for p in points]
        self.body = self.frame.add_text(text, rich=rich)   # always there (callers set its format)
        if not text:
            self.body.hide()
        words = _("Got it") if button is None else button
        self.ok_btn: QPushButton | None = None
        if words:
            self.ok_btn = self.frame.add_button(words, primary=True)
            self.ok_btn.clicked.connect(self.accept)
            self.ok_btn.setAutoDefault(True)
            QWidget.setTabOrder(self.ok_btn, self.close_btn)   # Got it first, then the ✕

    @property
    def panel_offset(self):
        """Where the visible panel starts inside the pop-up (the shadow's room)."""
        return self.frame.pos()

    def fit_height(self) -> None:
        """As tall as its words are at its width. (adjustSize asked the layout at a narrower
        width than the card's fixed one: the card came out too tall, the spare height
        spread round its title as empty bands.)"""
        lay = self.layout()
        if lay is not None:
            lay.activate()
        self.resize(self.width(), self.heightForWidth(self.width())
                    if self.hasHeightForWidth() else self.sizeHint().height())

    def place_at(self, x: int, y: int) -> None:
        """The pop-up's top-left at (`x`, `y`), moved just enough to be inside the window it
        opens from (narrower when that window is narrower than the card), and always on
        the screen. A narrow window at 150 % had the card run past its edge, over other
        programs."""
        room = self.screen().availableGeometry()
        win = self.parentWidget()
        inside = win.window().frameGeometry().intersected(room) if win is not None else room
        if inside.width() < self.width():
            self.setFixedWidth(max(NARROWEST + 2 * SHADOW, inside.width()))
        self.fit_height()
        across = inside if inside.width() >= self.width() else room
        down = inside if inside.height() >= self.height() else room
        self.move(max(across.left(), min(x, across.right() + 1 - self.width())),
                  max(down.top(), min(y, down.bottom() + 1 - self.height())))

    def showEvent(self, ev):   # noqa: N802 - Qt API
        shadow_tone(self._shadow)
        super().showEvent(ev)
        if self.ok_btn is not None:   # Enter = Got it (after Qt's own popup focus)
            QTimer.singleShot(0, self, self._focus_button)

    def _focus_button(self):
        if self.isVisible() and self.ok_btn is not None:
            self.ok_btn.setFocus(Qt.FocusReason.PopupFocusReason)

    def done(self, r):
        super().done(r)
        # the focus back on what opened it (a rail tab), not lost to the window: now and
        # again once Qt has finished closing the popup (it hands the focus on itself)
        self._give_focus_back()
        QTimer.singleShot(0, self._give_focus_back)

    def _give_focus_back(self):
        opener = self._opener
        if opener is not None and qt_valid(opener) and opener.isVisible():
            if not opener.window().isActiveWindow():   # (the popup had it)
                opener.window().activateWindow()
            opener.setFocus(Qt.FocusReason.PopupFocusReason)


class ModalDialog(QDialog):
    """A small modal on the shared frame (`confirm`, `ask_text`, `notice`): frameless, on a
    soft shadow, centred on its window. Esc and the ✕ cancel. `frame` is its ModalFrame."""

    def __init__(self, parent, title: str, *, mascot: str = "", icon: str = "",
                 tone: str = "info", width: int = DIALOG_W):
        super().__init__(owner(parent), Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle(title)
        self.setAccessibleName(title)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        screen = parent.screen() if parent is not None else QApplication.primaryScreen()
        self.setFixedWidth(min(width + 2 * SHADOW, screen.availableGeometry().width() - 24))
        outer = QVBoxLayout(self)
        self.frame = ModalFrame(title, mascot=mascot, icon=icon, tone=tone)
        outer.addWidget(self.frame)
        self._shadow = add_shadow(self, self.frame)
        self.frame.close_btn.clicked.connect(self.reject)
        self._first: QWidget | None = None   # what has the focus when it opens
        # the helper's own parts, set by confirm / ask_text / notice
        self.yes_btn: QPushButton | None = None   # the verb (Got it for notice)
        self.no_btn: QPushButton | None = None    # Cancel
        self.edit: QLineEdit | None = None        # ask_text's box
        self.combo: QComboBox | None = None       # ask_choice's dropdown
        self.kind = ""   # which helper made it: "confirm", "ask_text", "ask_choice", "notice"
        from soundboard.ui.kit import fit
        fit.watch(self)

    def focus_first(self, w: QWidget) -> None:
        """`w` gets the focus when it opens (the safe button, or the text box)."""
        self._first = w

    def showEvent(self, ev):   # noqa: N802 - Qt API
        shadow_tone(self._shadow)
        lay = self.layout()
        if lay is not None:
            lay.activate()   # wrapped text: as tall as the words need
        # as wide as its row of buttons needs (four of them, or German: about 600 px), so
        # none is cut; never wider than the screen
        inner = self.frame.layout()
        side = 0
        if inner is not None:
            fm = inner.contentsMargins()
            side = fm.left() + fm.right()
        edge = self.frame.width() - self.frame.contentsRect().width()   # its border
        need = self.frame._foot.sizeHint().width() + side + edge + 2 * SHADOW
        if self.frame._lefts:
            need += 16   # a gap between the left buttons and the rest
        room = self.screen().availableGeometry()
        if need > self.width():
            self.setFixedWidth(min(need, room.width() - 24))
            if lay is not None:
                lay.activate()
        self.resize(self.width(), self.heightForWidth(self.width()) if self.hasHeightForWidth()
                    else self.sizeHint().height())
        owner = self.parentWidget()
        area = owner.window().frameGeometry() if owner is not None else room
        x = area.center().x() - self.width() // 2
        y = area.center().y() - self.height() // 2
        self.move(max(room.left(), min(x, room.right() - self.width() + 1)),
                  max(room.top(), min(y, room.bottom() - self.height() + 1)))
        super().showEvent(ev)
        if self._first is not None:
            QTimer.singleShot(0, self, self._focus)

    def _focus(self):
        if self.isVisible() and self._first is not None:
            self._first.setFocus(Qt.FocusReason.OtherFocusReason)


def confirm(parent, title: str, text: str, verb: str, *, danger: bool = False,
            mascot: str = "", rich: bool = False, keep_open: bool = False) -> bool:
    """Ask a yes / no question: `text` says what happens, `verb` is the button that does it
    ("Delete for good"), then Cancel. True if `verb` was pressed. `danger`: the verb in the
    danger style (it can't be undone). Enter, Esc, the ✕ and a click outside are Cancel;
    `keep_open`: a click outside does nothing (a question the user must answer)."""
    dlg = ModalDialog(parent, title, mascot=mascot)
    if keep_open:
        from soundboard.ui.kit import modals
        modals.keep_open(dlg)
    if text:   # (no words: no empty gap above the buttons)
        dlg.frame.add_text(text, rich=rich)
    yes = dlg.frame.add_button(verb, primary=not danger, danger=danger)
    no = dlg.frame.add_button(_("Cancel"))
    yes.setDefault(False)
    no.setDefault(True)   # the safe one on Enter
    yes.clicked.connect(dlg.accept)
    no.clicked.connect(dlg.reject)
    dlg.focus_first(no)
    dlg.yes_btn, dlg.no_btn = yes, no
    dlg.kind = "confirm"
    _opened(dlg)
    return dlg.exec() == QDialog.DialogCode.Accepted


def ask_text(parent, title: str, label: str, text: str = "", *, verb: str | None = None,
             max_len: int = 0, hint: str = "") -> str | None:
    """Ask for one line of text (a name): `label` above the box, `text` in it (selected),
    `hint` as its placeholder, at most `max_len` characters (0: no limit). `verb` (default
    Save) can't be pressed while the box is empty; Enter in the box presses it. The text,
    trimmed, or None on Cancel / Esc / ✕. Typed text isn't lost to a click outside."""
    from soundboard.ui.kit.modals import keep_open
    dlg = ModalDialog(parent, title)
    keep_open(dlg)
    lbl = dlg.frame.add_text(label)
    edit = QLineEdit(text)
    edit.setPlaceholderText(hint)
    if max_len:
        edit.setMaxLength(max_len)
    edit.setAccessibleName(label)
    lbl.setBuddy(edit)
    edit.selectAll()
    dlg.frame.add_widget(edit)
    save = dlg.frame.add_button(_("Save") if verb is None else verb, primary=True)
    cancel = dlg.frame.add_button(_("Cancel"))
    save.setEnabled(bool(text.strip()))
    edit.textChanged.connect(lambda t: save.setEnabled(bool(t.strip())))
    save.clicked.connect(dlg.accept)
    cancel.clicked.connect(dlg.reject)
    dlg.focus_first(edit)
    dlg.edit, dlg.yes_btn, dlg.no_btn = edit, save, cancel
    dlg.kind = "ask_text"
    _opened(dlg)
    if dlg.exec() != QDialog.DialogCode.Accepted or not edit.text().strip():
        return None
    return edit.text().strip()


def ask_choice(parent, title: str, label: str, items, *, verb: str | None = None,
               current: int = 0) -> str | None:
    """Pick one of `items` (texts) from a dropdown, `label` above it, `current` picked to
    start with. `verb` (default Done) then Cancel; Enter presses `verb`. The picked text, or
    None on Cancel / Esc / ✕ / a click outside (or with no items)."""
    items = list(items)
    dlg = ModalDialog(parent, title)
    lbl = dlg.frame.add_text(label)
    box = QComboBox()
    box.addItems(items)
    if items:
        box.setCurrentIndex(max(0, min(current, len(items) - 1)))
    box.setAccessibleName(label)
    box.setMinimumWidth(200)   # (a short list's words alone made it a stub)
    lbl.setBuddy(box)
    dlg.frame.add_widget(box)
    ok = dlg.frame.add_button(_("Done") if verb is None else verb, primary=True)
    cancel = dlg.frame.add_button(_("Cancel"))
    ok.setEnabled(bool(items))
    ok.clicked.connect(dlg.accept)
    cancel.clicked.connect(dlg.reject)
    dlg.focus_first(box)
    dlg.combo, dlg.yes_btn, dlg.no_btn = box, ok, cancel
    dlg.kind = "ask_choice"
    _opened(dlg)
    if dlg.exec() != QDialog.DialogCode.Accepted or not items:
        return None
    return box.currentText()


NOTICE = {"info": ("info", "info"), "warning": ("warn", "warn"), "error": ("alert", "error")}


def notice(parent, title: str, text: str, *, kind: str = "info", verb: str | None = None,
           rich: bool = False) -> None:
    """Tell the user something that needs a click (in place of QMessageBox.information /
    warning / critical): the kind's icon ("info", "warning", "error") by the title, `text`,
    one button (`verb`, default Got it). For news that needs no click, use busy.toast."""
    icon, tone = NOTICE.get(kind, NOTICE["info"])
    dlg = ModalDialog(parent, title, icon=icon, tone=tone)
    dlg.frame.add_text(text, rich=rich)
    ok = dlg.frame.add_button(_("Got it") if verb is None else verb, primary=True)
    ok.clicked.connect(dlg.accept)
    dlg.focus_first(ok)
    dlg.yes_btn = ok
    dlg.kind = "notice"
    _opened(dlg)
    dlg.exec()


def _opened(dlg: ModalDialog) -> None:
    """Each helper's dialog, just before it opens. Tests: an unanswered one fails at once
    (conftest's guard); the `modal_answers` fixture answers them on purpose."""
