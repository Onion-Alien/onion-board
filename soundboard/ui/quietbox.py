"""No Windows "ding" from everyday message boxes, and the app's look on Qt's stock boxes.

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

from PySide6.QtCore import QEvent, QObject, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QDialogButtonBox, QInputDialog, QLabel, QLayout,
                               QMessageBox)

_ICONS = {   # box icon -> (painted icon, theme tone)
    QMessageBox.Icon.Question: ("question", "accent_text"),
    QMessageBox.Icon.Information: ("info", "accent_text"),
    QMessageBox.Icon.Warning: ("warn", "warn_text"),
}
BADGE = 40          # the round badge; the icon inside it is 24
TEXT_MIN = 300      # a box's text is at least this wide, so short ones aren't cramped
INPUT_MIN = 360     # an ask-for-a-name box's width


def badge(name: str, tone: str, ratio: float = 1.0) -> QPixmap:
    """`name` (ui/icons.py) in the theme's `tone` on a circle of the same tone, faint."""
    from soundboard import theme
    from soundboard.ui import icons
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
        label.setMinimumWidth(TEXT_MIN)
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


class _Filter(QObject):
    def eventFilter(self, obj, event):   # noqa: N802 - Qt API
        # Polish comes before the box is sized; Show (before its showEvent, which
        # plays the sound and sizes the box) catches an icon or text set after that
        if event.type() in (QEvent.Type.Polish, QEvent.Type.Show):
            if isinstance(obj, QMessageBox):
                silence(obj)
                if event.type() == QEvent.Type.Show:
                    tidy(obj)
            elif isinstance(obj, QInputDialog) and event.type() == QEvent.Type.Show:
                tidy_input(obj)
        return False


def install(app: QApplication) -> None:
    """Silence and restyle every Information/Warning/Question QMessageBox (and tidy
    every QInputDialog) the app shows from now on."""
    from soundboard import theme
    f = _Filter(app)
    app._quietbox_filter = f   # pyright: ignore[reportAttributeAccessIssue]  # kept alive with the app
    theme.app_filter(app, f)   # (sits out theme switches: no boxes made)
