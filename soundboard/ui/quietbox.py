"""No Windows "ding" from everyday message boxes.

On Windows, Qt plays a system sound whenever a QMessageBox with the Information or
Warning icon is shown (SystemAsterisk / SystemExclamation, chosen from the box's
`icon` property). For a soundboard that's noise: a tip or a "couldn't copy that"
note isn't an alarm, and the ding can land in the middle of whatever the user is
playing or saying. So every such box gets the same picture as a pixmap instead —
it looks identical, but its `icon` is NoIcon, which Qt plays nothing for.

Critical boxes keep their sound: that's reserved for things really going wrong.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QSize
from PySide6.QtWidgets import QApplication, QMessageBox, QStyle

_SILENCED = {
    QMessageBox.Icon.Information: QStyle.StandardPixmap.SP_MessageBoxInformation,
    QMessageBox.Icon.Warning: QStyle.StandardPixmap.SP_MessageBoxWarning,
}


def silence(box: QMessageBox) -> None:
    """Swap an Information/Warning icon for the same picture, so no sound plays."""
    sp = _SILENCED.get(box.icon())
    if sp is None:
        return
    style = box.style()
    size = style.pixelMetric(QStyle.PixelMetric.PM_MessageBoxIconSize, None, box)
    pix = style.standardIcon(sp, None, box).pixmap(QSize(size, size),
                                                    box.devicePixelRatioF())
    box.setIconPixmap(pix)   # also sets icon() to NoIcon


class _Filter(QObject):
    def eventFilter(self, obj, event):   # noqa: N802 - Qt API
        # Polish comes before the box is sized; Show (before its showEvent, which
        # plays the sound) catches an icon set after that
        if (event.type() in (QEvent.Type.Polish, QEvent.Type.Show)
                and isinstance(obj, QMessageBox)):
            silence(obj)
        return False


def install(app: QApplication) -> None:
    """Silence every Information/Warning QMessageBox the app shows from now on."""
    app._quietbox_filter = _Filter(app)   # kept alive with the app
    app.installEventFilter(app._quietbox_filter)
