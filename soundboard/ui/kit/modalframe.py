"""The one look for pop-up cards and small modals (DESIGN.md *Standard kit*, *Modal frame*).

`ModalFrame` is the panel: a rounded, raised surface with a header (a small mascot, the
title, a one-line subtitle and a ✕), a body of short points that each have an icon, and a
footer with the card's one main button. Put it in any dialog. `InfoCard` is the ready-made
pop-up around it: frameless, on a soft shadow, it closes on Esc, the ✕, its button or a
click outside, and gives the focus back to what opened it.

Its look comes from the app style sheet (`#modalframe`, `#modalpointicon`, ...), so it
follows every theme; nothing here sets a colour or a font size.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QGraphicsDropShadowEffect,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
                               QWidget)
from shiboken6 import isValid as qt_valid

from soundboard.i18n import _
from soundboard.ui.kit import icons, theme
from soundboard.ui.kit.panel import icon_button

WIDTH = 480      # the panel's width (a pop-up card); dialogs stay <= 620 (DESIGN.md)
MASCOT = 56      # the mascot's height in the header
SHADOW = 16      # room round an InfoCard's panel for its shadow
BADGE = 32       # a point's icon square
GLYPH = 18       # the icon in it
GAP = 14         # between the icon column and the words
DIALOG_W = 440   # a small modal's panel (confirm / ask_text / notice)
TONES = {"info": "accent_text", "warn": "warn_text", "error": "error_text"}


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
    (QLabel#muted, hidden when empty), `mascot`, `icon`, `close_btn`, `body` (a
    QVBoxLayout: add_point / add_text / add_widget fill it) and `footer` (a QHBoxLayout,
    shown once add_button has put a button in it)."""

    def __init__(self, title: str, subtitle: str = "", *, mascot: str = "bun",
                 icon: str = "", tone: str = "info", close: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("modalframe")
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 20, 20)   # 20 on the right: the ✕ sits in its corner
        v.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(GAP)
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

        v.addSpacing(18)
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
        self._foot.hide()
        v.addWidget(self._foot)

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
        leading = self.mascot is not None or self.icon is not None
        row.setContentsMargins(self.lead + GAP if leading else 0, 0, 0, 0)
        row.addWidget(lbl)
        self.body.addLayout(row)
        return lbl

    def add_widget(self, w: QWidget) -> QWidget:
        """Any other part of the body (a text box), on the title's edge like the words."""
        row = QHBoxLayout()
        leading = self.mascot is not None or self.icon is not None
        row.setContentsMargins(self.lead + GAP if leading else 0, 0, 0, 0)
        row.addWidget(w)
        self.body.addLayout(row)
        return w

    def add_button(self, text: str, *, primary: bool = False,
                   danger: bool = False) -> QPushButton:
        """A footer button, right-aligned, in the order added (the main one first: DESIGN.md
        *Dialog anatomy*). `primary`: the card's one filled button; `danger`: a verb that
        can't be undone (#danger)."""
        b = QPushButton(text)
        if danger:   # (named before it's in a layout: once styled, a new name changes nothing)
            b.setObjectName("danger")
        elif primary:
            b.setObjectName("primary")
            b.setDefault(True)
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
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._opener = QApplication.focusWidget()
        self.setWindowTitle(title)
        self.setAccessibleName(title)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        room = self.screen().availableGeometry().width() - 24
        self.setFixedWidth(min(width + 2 * SHADOW, room))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW, SHADOW // 2, SHADOW, SHADOW + 4)   # shadow falls down
        self.frame = ModalFrame(title, subtitle, mascot=mascot)
        self._shadow = QGraphicsDropShadowEffect(self.frame)
        self._shadow.setBlurRadius(32)
        self._shadow.setOffset(0, 6)
        self.frame.setGraphicsEffect(self._shadow)
        outer.addWidget(self.frame)
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

    def showEvent(self, ev):   # noqa: N802 - Qt API
        # (the theme now: a dark theme needs a deeper shadow to show at all)
        self._shadow.setColor(QColor(0, 0, 0, 60 if theme.is_light() else 150))
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
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle(title)
        self.setAccessibleName(title)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        screen = parent.screen() if parent is not None else QApplication.primaryScreen()
        self.setFixedWidth(min(width + 2 * SHADOW, screen.availableGeometry().width() - 24))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW, SHADOW // 2, SHADOW, SHADOW + 4)   # shadow falls down
        self.frame = ModalFrame(title, mascot=mascot, icon=icon, tone=tone)
        self._shadow = QGraphicsDropShadowEffect(self.frame)
        self._shadow.setBlurRadius(32)
        self._shadow.setOffset(0, 6)
        self.frame.setGraphicsEffect(self._shadow)
        outer.addWidget(self.frame)
        self.frame.close_btn.clicked.connect(self.reject)
        self._first: QWidget | None = None   # what has the focus when it opens
        # the helper's own parts, set by confirm / ask_text / notice
        self.yes_btn: QPushButton | None = None   # the verb (Got it for notice)
        self.no_btn: QPushButton | None = None    # Cancel
        self.edit: QLineEdit | None = None        # ask_text's box
        from soundboard.ui.kit import fit
        fit.watch(self)

    def focus_first(self, w: QWidget) -> None:
        """`w` gets the focus when it opens (the safe button, or the text box)."""
        self._first = w

    def showEvent(self, ev):   # noqa: N802 - Qt API
        self._shadow.setColor(QColor(0, 0, 0, 60 if theme.is_light() else 150))
        lay = self.layout()
        if lay is not None:
            lay.activate()   # wrapped text: as tall as the words need
        self.resize(self.width(), self.heightForWidth(self.width()) if self.hasHeightForWidth()
                    else self.sizeHint().height())
        owner = self.parentWidget()
        room = self.screen().availableGeometry()
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
            mascot: str = "", rich: bool = False) -> bool:
    """Ask a yes / no question: `text` says what happens, `verb` is the button that does it
    ("Delete for good"), then Cancel. True if `verb` was pressed. `danger`: the verb in the
    danger style (it can't be undone). Enter, Esc, the ✕ and a click outside are Cancel."""
    dlg = ModalDialog(parent, title, mascot=mascot)
    dlg.frame.add_text(text, rich=rich)
    yes = dlg.frame.add_button(verb, primary=not danger, danger=danger)
    no = dlg.frame.add_button(_("Cancel"))
    yes.setDefault(False)
    no.setDefault(True)   # the safe one on Enter
    yes.clicked.connect(dlg.accept)
    no.clicked.connect(dlg.reject)
    dlg.focus_first(no)
    dlg.yes_btn, dlg.no_btn = yes, no
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
    _opened(dlg)
    if dlg.exec() != QDialog.DialogCode.Accepted or not edit.text().strip():
        return None
    return edit.text().strip()


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
    _opened(dlg)
    dlg.exec()


def _opened(dlg: ModalDialog) -> None:
    """Each helper's dialog, just before it opens (tests swap this to look at it)."""
