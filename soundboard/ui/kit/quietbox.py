"""The app's small modals, and no Windows "ding" from Qt's stock message boxes.

`ask`, `tell` and `get_text` are the app's questions, notes and ask-for-a-name boxes, in
place of QMessageBox.question / .information and QInputDialog.getText: a `ModalCard`, the
shared card frame (kit/modalframe.py) as a modal of its own. It has no Windows title bar:
the card's own heading and ✕ are the title and the way out, it lies on a soft shadow,
opens centred on its window and is dragged by any empty spot. Buttons say what they do
("Remove", never Yes / No); the main one is filled, one that throws something away is red.

Stock boxes that are still shown (Qt's own, older code):
On Windows, Qt plays a system sound whenever a QMessageBox with the Information or
Warning icon is shown (SystemAsterisk / SystemExclamation, chosen from the box's
`icon` property). For a soundboard that's noise: a tip or a "couldn't copy that"
note isn't an alarm, and the ding can land in the middle of whatever the user is
playing or saying. So every such box gets a picture instead: its `icon` is NoIcon,
which Qt plays nothing for.

The picture is the app's own painted icon on a soft round badge in the theme's tone
(accent for a question or a note, the warning colour for a warning), not Qt's stock
bitmaps, and a plain-text box's first paragraph becomes its bold heading with the
rest under it. Qt's ask-for-a-name boxes (QInputDialog) get the same room and the
main button filled. Critical boxes keep their sound: that's reserved for things
really going wrong.
"""
from __future__ import annotations

import re
from typing import TypeVar

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QInputDialog, QLabel,
                               QLayout, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
                               QWidget)

_ICONS = {   # box icon -> (painted icon, theme tone)
    QMessageBox.Icon.Question: ("question", "accent_text"),
    QMessageBox.Icon.Information: ("info", "accent_text"),
    QMessageBox.Icon.Warning: ("warn", "warn_text"),
}
BADGE = 40          # the round badge; the icon inside it is 24
TEXT_MIN = 300      # a box's text is at least this wide, so short ones aren't cramped
INPUT_MIN = 360     # an ask-for-a-name box's width


def badge(name: str, tone: str, ratio: float = 1.0) -> QPixmap:
    """`name` (ui/kit/icons.py) in the theme's `tone` on a circle of the same tone, faint."""
    from soundboard.ui.kit import theme
    from soundboard.ui.kit import icons
    col = QColor(theme.T.get(tone, tone))
    pm = QPixmap(round(BADGE * ratio), round(BADGE * ratio))
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    ring = QColor(col)
    ring.setAlphaF(0.16)
    p.setBrush(ring)
    p.drawEllipse(QRectF(0, 0, BADGE, BADGE))
    inner = icons.pixmap(name, round(24 * ratio), col.name())
    inner.setDevicePixelRatio(ratio)
    p.drawPixmap(8, 8, inner)
    p.end()
    return pm


def silence(box: QMessageBox) -> None:
    """Swap a Question/Information/Warning icon for the app's badge, so no sound plays."""
    spec = _ICONS.get(box.icon())
    if spec is None:
        return
    box.setIconPixmap(badge(*spec, ratio=box.devicePixelRatioF()))   # icon() is NoIcon now


def tidy(box: QMessageBox) -> None:
    """Heading + text, room around them. Once per box; a box with its own informative
    text or rich text keeps it as it is."""
    if box.property("tidied"):
        return
    box.setProperty("tidied", True)
    text = box.text()
    if (box.textFormat() != Qt.TextFormat.RichText and not re.search(r"<[a-z/!][^>]*>", text, re.I)
            and not box.informativeText() and "\n\n" in text):
        head, rest = text.split("\n\n", 1)
        if head.strip() and rest.strip():
            box.setText(head)
            box.setInformativeText(rest)
    lay = box.layout()
    if isinstance(lay, QLayout):
        lay.setContentsMargins(20, 18, 20, 16)
    label = box.findChild(QLabel, "qt_msgbox_label")
    if label is not None:
        if box.informativeText():
            f = label.font()
            f.setBold(True)
            f.setPointSizeF(f.pointSizeF() * 1.1)
            label.setFont(f)
        # Only text shorter than TEXT_MIN gets the minimum: QMessageBox measures the
        # unwrapped label to decide whether to wrap it, and a fixed minimum hides a
        # long line's width, so on a wide screen it stayed one line and was cut off.
        wrap = label.wordWrap()
        label.setWordWrap(False)
        if label.sizeHint().width() < TEXT_MIN:
            label.setMinimumWidth(TEXT_MIN)
        label.setWordWrap(wrap)
    icon = box.findChild(QLabel, "qt_msgboxex_icon_label")
    if icon is not None:
        icon.setContentsMargins(0, 0, 6, 0)
        icon.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)


def tidy_input(dlg: QInputDialog) -> None:
    """Room around an ask-for-a-name box, and its OK as the filled main button."""
    if dlg.property("tidied"):
        return
    dlg.setProperty("tidied", True)
    lay = dlg.layout()
    if isinstance(lay, QLayout):
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
    dlg.setMinimumWidth(INPUT_MIN)
    bb = dlg.findChild(QDialogButtonBox)
    ok = bb.button(QDialogButtonBox.StandardButton.Ok) if bb is not None else None
    if ok is not None:
        ok.setObjectName("primary")
        ok.style().unpolish(ok)
        ok.style().polish(ok)


def _polished(w) -> None:
    """Every widget as the app style polishes it (wheelguard.on_polish): a box is
    silenced before it's sized, and watched for its Show."""
    if isinstance(w, QMessageBox):
        silence(w)
        w.installEventFilter(_show_filter())   # once: Qt doesn't add it twice
    elif isinstance(w, QInputDialog):
        w.installEventFilter(_show_filter())


class _Filter(QObject):
    """On each message box and ask-for-a-name box only, never the whole app (an
    application filter is called for every event of every object). Show comes before
    the box's showEvent, which plays the sound and sizes the box: it catches an icon
    or text set after the box was polished."""

    def eventFilter(self, obj, event):   # noqa: N802 - Qt API
        if event.type() == QEvent.Type.Show:
            if isinstance(obj, QMessageBox):
                silence(obj)
                tidy(obj)
            elif isinstance(obj, QInputDialog):
                tidy_input(obj)
        return False


_filter: _Filter | None = None


def _show_filter() -> _Filter:
    global _filter
    if _filter is None:
        _filter = _Filter()
    return _filter


def install(app: QApplication) -> None:
    """Silence and restyle every Information/Warning/Question QMessageBox (and tidy
    every QInputDialog) the app shows from now on."""
    from soundboard.ui.kit import wheelguard
    wheelguard.on_polish(_polished)


# ---------------------------------------------------------------------------- the app's own
SHADOW = 16     # room round the card for its shadow (as modalframe.InfoCard)
DISMISSED = -1  # ask(): Esc, the ✕ or a click outside
_W = TypeVar("_W", bound=QWidget)


class ModalCard(QDialog):
    """A small modal on the shared card frame (kit/modalframe.py, DESIGN.md *Modal frame*).

    `icon` (a name in icons.SHAPES) on a soft badge in `tone`, or `mascot` ("bun" / "owl"),
    left of the `title`; `subtitle` a quieter line under it; `text` the body's first
    paragraph (`body`, None without text). Fill it with add_text / add_widget /
    add_button; `clicked` is the button that closed it (None: Esc, the ✕, a click
    outside). `width`: the card's, without the shadow."""

    def __init__(self, title: str, text: str = "", *, subtitle: str = "", icon: str = "",
                 tone: str = "accent_text", mascot: str = "", rich: bool = False,
                 width: int | None = None, parent=None):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        from soundboard.ui.kit import fit, modalframe
        fit.watch(self)   # grows to fit long translations (ui/kit/fit.py)
        self.setWindowTitle(title)   # (the taskbar's and a screen reader's name)
        self.setAccessibleName(title)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.clicked: QPushButton | None = None
        self.buttons: list[QPushButton] = []   # the footer's, in the order added
        self._drag: QPoint | None = None
        self._first: QWidget | None = None   # what has the focus when it opens
        width = modalframe.WIDTH if width is None else width
        room = self.screen().availableGeometry().width() - 24
        self.setFixedWidth(min(width + 2 * SHADOW, room))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW, SHADOW // 2, SHADOW, SHADOW + 4)   # shadow falls down
        self.frame = modalframe.ModalFrame(title, subtitle, mascot=mascot)
        if icon and not mascot:
            self._badge(icon, tone)
        outer.addWidget(self.frame)
        self.heading, self.subtitle = self.frame.heading, self.frame.subtitle
        self.close_btn = self.frame.close_btn
        self.close_btn.clicked.connect(self.reject)
        self.close_btn.setAutoDefault(False)   # (Enter never presses the ✕)
        self.body: QLabel | None = self.add_text(text, rich=rich) if text else None

    def _badge(self, icon: str, tone: str):
        """The icon on its round badge where the mascot goes."""
        mark = QLabel()
        mark.setObjectName("modalmascot")
        mark.setPixmap(badge(icon, tone, self.devicePixelRatioF() or 1.0))
        mark.setFixedSize(BADGE, BADGE)
        self._put_mascot(mark, Qt.AlignmentFlag.AlignTop)

    def _put_mascot(self, w: QWidget, align=Qt.AlignmentFlag.AlignVCenter):
        """`w` (a badge, a moving Bun) as the header's first item, the mascot's place; call
        it before adding anything to the body (the words start on the title's line)."""
        from PySide6.QtWidgets import QBoxLayout
        lay = self.frame.layout()
        item = lay.itemAt(0) if lay is not None else None
        header = item.layout() if item is not None else None
        if not isinstance(header, QBoxLayout):
            return
        old = self.frame.mascot
        if old is not None:
            header.removeWidget(old)
            old.deleteLater()
        header.insertWidget(0, w, 0, align)
        # (a moving Bun is a QWidget, not the QLabel the frame's own mascot is)
        self.frame.mascot = w  # pyright: ignore[reportAttributeAccessIssue]
        self.frame.lead = w.width()

    def add_text(self, text: str, *, rich: bool = False) -> QLabel:
        return self.frame.add_text(text, rich=rich)

    def add_widget(self, w: _W, stretch: int = 0, *, flush: bool = False) -> _W:
        """`w` in the body, on the title's edge like the text; with `flush` the card's
        whole width (a wide table or log)."""
        from PySide6.QtWidgets import QHBoxLayout
        from soundboard.ui.kit.modalframe import GAP
        row = QHBoxLayout()
        indent = self.frame.mascot is not None and not flush
        row.setContentsMargins(self.frame.lead + GAP if indent else 0, 0, 0, 0)
        row.addWidget(w)
        self.frame.body.addLayout(row, stretch)
        _see_through(w)
        return w

    def add_button(self, words: str, kind: str = "", *, closes: bool = True,
                   left: bool = False) -> QPushButton:
        """A footer button, right-aligned in the order added (the main one first), or with
        `left` at the footer's left. `kind`: "primary" (the one filled button), "danger"
        (it throws something away: red) or "" (plain). `closes`: clicking it closes the
        card, with `clicked` set to it."""
        b = self.frame.add_button(words, primary=kind == "primary")
        self.buttons.append(b)
        if kind == "danger":
            b.setObjectName("danger")
            b.setDefault(True)
            b.style().unpolish(b)   # (styled as the new name)
            b.style().polish(b)
        if left:   # before the footer's stretch
            self.frame.footer.removeWidget(b)
            self.frame.footer.insertWidget(self._lefts(), b)
        if closes:
            b.clicked.connect(lambda _c=False, b=b: self._chose(b))
        return b

    def _lefts(self) -> int:
        """How many buttons sit left of the footer's stretch."""
        f = self.frame.footer
        for i in range(f.count()):
            it = f.itemAt(i)
            if it is not None and it.spacerItem() is not None:
                return i
        return 0

    def set_default(self, b: QPushButton):
        """Enter presses `b` (and nothing else), and it has the focus."""
        for other in self.findChildren(QPushButton):
            other.setDefault(other is b)
        b.setFocus()
        self._first = b

    def _chose(self, b: QPushButton):
        self.clicked = b
        self.accept()

    def snug(self):
        """As tall as its words need at its width, no taller: a first guess from Qt (it
        measures wrapped words at a narrower width) left a band of empty card under the
        title, and fit.watch never shrinks a window."""
        lay = self.layout()
        if lay is None:
            return
        self.ensurePolished()   # (the sheet's fonts on every label first: they set the height)
        for w in self.findChildren(QWidget):
            w.ensurePolished()
        lay.invalidate()
        lay.activate()
        # wide enough for its row of buttons (a long translation, a wide theme font):
        # squeezed, Qt cut their words off
        foot = self.frame.findChild(QWidget, "modalfoot")
        fl = self.frame.layout()
        if foot is not None and fl is not None and foot.isVisibleTo(self):
            fm = fl.contentsMargins()
            need = foot.sizeHint().width() + fm.left() + fm.right() + 2 * SHADOW + 2
            room = self.screen().availableGeometry().width() - 24
            if need > self.width():
                self.setFixedWidth(min(need, room))
                lay.activate()
        h = max(lay.totalHeightForWidth(self.width()), lay.totalMinimumSize().height())
        if h > 0 and h != self.height():
            self.resize(self.width(), h)

    def showEvent(self, ev):   # noqa: N802 - Qt API
        self.snug()
        super().showEvent(ev)
        QTimer.singleShot(0, self, self.snug)   # again once it's on screen, styled
        first = self._first
        if first is not None:
            first.setFocus()

    def paintEvent(self, ev):   # noqa: N802 - Qt API
        """The soft shadow under the card: rings of fading black round its edge (a
        QGraphicsEffect would redraw the whole card, lists and all, on every change)."""
        from soundboard.ui.kit import theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        r = QRectF(self.frame.geometry()).translated(0, 4)
        strength = 26 if theme.is_light() else 60
        for i in range(SHADOW, 0, -2):
            path = QPainterPath()
            path.addRoundedRect(r.adjusted(-i, -i * 0.6, i, i), 16 + i, 16 + i)
            p.setBrush(QColor(0, 0, 0, round(strength * (1 - i / SHADOW) ** 2 / 4) + 1))
            p.drawPath(path)
        p.end()

    # a card with no title bar moves by any empty spot of it
    def mousePressEvent(self, e):   # noqa: N802 - Qt API
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.pos()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):   # noqa: N802 - Qt API
        if self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):   # noqa: N802 - Qt API
        self._drag = None
        super().mouseReleaseEvent(e)


_PLAIN = ("QWidget", "QStackedWidget", "QCheckBox", "QRadioButton")


def _see_through(w: QWidget) -> None:
    """`w` and the plain boxes and ticks in it show the card under them: the app's sheet
    gives every widget the window's colour (`QWidget { background:$bg }`), a dark slab on
    the card's. Named as the frame's own see-through parts (#modalpoint); a widget that
    has a name of its own keeps its look."""
    for c in [w, *w.findChildren(QWidget)]:
        if not c.objectName() and type(c).__name__ in _PLAIN:
            c.setObjectName("modalpoint")
            c.style().unpolish(c)   # (it may be styled already: measuring a layout does it)
            c.style().polish(c)


def split(text: str) -> tuple[str, str]:
    """(the first paragraph, the rest): a short question as the card's heading, what it
    means under it."""
    head, _sep, rest = text.partition("\n\n")
    return head.strip(), rest.strip()


def run(box: ModalCard) -> QPushButton | None:
    """Open `box` (modal), free it once it's closed; the button that closed it, or None."""
    box.exec()
    clicked = box.clicked
    from soundboard.ui.kit.crashdialog import free_dialog
    free_dialog(box)
    return clicked


def ask(parent, title: str, text: str, buttons, *, default: int | None = None,
        icon: str = "question", tone: str = "accent_text", subtitle: str = "",
        rich: bool = False) -> int:
    """A question with its answers as buttons: `buttons` = [(words, kind), ...], main first
    (kind: "primary", "danger" or ""). Returns the index of the one clicked, or DISMISSED
    (Esc, the ✕, a click outside: the same as Cancel). `default`: the button Enter presses
    (the first otherwise); for something that throws work away, the Cancel."""
    box = ModalCard(title, text, subtitle=subtitle, icon=icon, tone=tone, rich=rich,
                    parent=parent)
    made = [box.add_button(words, kind) for words, kind in buttons]
    if made:
        box.set_default(made[default if default is not None else 0])
    clicked = run(box)
    return made.index(clicked) if clicked in made else DISMISSED


def tell(parent, title: str, text: str, *, icon: str = "info", tone: str = "accent_text",
         button: str | None = None, rich: bool = False) -> None:
    """A note to read, with one button (*Got it*)."""
    from soundboard.i18n import _
    box = ModalCard(title, text, icon=icon, tone=tone, rich=rich, parent=parent)
    box.set_default(box.add_button(_("Got it") if button is None else button, "primary"))
    run(box)


def get_text(parent, title: str, label: str, text: str = "", *, ok: str | None = None,
             icon: str = "edit") -> tuple[str, bool]:
    """Ask for a name: `label` above a text box holding `text`. Returns (what was typed,
    True) on `ok` (*OK*) or Enter, ("", False) otherwise."""
    from soundboard.i18n import _
    box = ModalCard(title, label, icon=icon, parent=parent)
    line = QLineEdit(text)
    line.setAccessibleName(label)
    box.add_widget(line)
    go = box.add_button(_("OK") if ok is None else ok, "primary")
    box.add_button(_("Cancel"))
    line.returnPressed.connect(go.click)
    line.selectAll()
    box._first = line   # typing goes straight in
    go.setDefault(True)
    box.exec()
    got = (line.text(), True) if box.clicked is go else ("", False)
    from soundboard.ui.kit.crashdialog import free_dialog
    free_dialog(box)
    return got
