"""A tab's help pop-up (`TabHelpPopup`): the ? button's few lines on what the tab is for, with
Bun or Hoot beside them. `dialogs` re-exports it."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QVBoxLayout
from shiboken6 import isValid as qt_valid

from soundboard.i18n import _
from soundboard.ui.kit.panel import icon_button


class TabHelpPopup(QDialog):
    """A compact help card with a mascot: Escape, the close button or a click outside
    closes it, and the focus goes back to what opened it. Its look comes from the
    shared style sheet (`#helpcard`, `#helptitle`, `#helpbody`), so it follows the theme."""

    def __init__(self, title: str, text: str, *, owl: bool = False, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        from soundboard.ui.bun.bunny import bunny_pixmap
        from soundboard.style.owl import owl_image

        self._opener = QApplication.focusWidget()
        self.setWindowTitle(title)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(min(560, self.screen().availableGeometry().width() - 24))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame = QFrame()
        frame.setObjectName("helpcard")
        outer.addWidget(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(16)

        header = QHBoxLayout()
        self.heading = QLabel(title)
        self.heading.setObjectName("helptitle")
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        self.heading.setWordWrap(True)
        header.addWidget(self.heading, 1)
        self.close_btn = icon_button("close", _("Close"), size=16)
        self.close_btn.clicked.connect(self.reject)
        header.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        content = QHBoxLayout()
        content.setSpacing(22)
        self.mascot = QLabel()
        self.mascot.setFixedSize(88, 104)
        self.mascot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dpr = self.devicePixelRatioF()
        picture = (QPixmap.fromImage(owl_image(round(92 * dpr), look=0.0))
                   if owl else bunny_pixmap(92, dpr=dpr))
        picture.setDevicePixelRatio(dpr)
        self.mascot.setPixmap(picture)
        content.addWidget(self.mascot, 0, Qt.AlignmentFlag.AlignVCenter)
        self.body = QLabel(text)
        self.body.setObjectName("helpbody")
        self.body.setTextFormat(Qt.TextFormat.PlainText)
        self.body.setWordWrap(True)
        content.addWidget(self.body, 1, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(content)

    def done(self, r):
        super().done(r)
        # the focus back on what opened it (a rail tab), not lost to the window
        if self._opener is not None and qt_valid(self._opener) and self._opener.isVisible():
            self._opener.setFocus(Qt.FocusReason.PopupFocusReason)
