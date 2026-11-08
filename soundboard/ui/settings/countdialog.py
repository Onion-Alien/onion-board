"""*What Count me in sends*: the eye button beside Settings' Count me in opens this
small table (what, an example, why), so the setting itself stays one line and the
whole list is one click away. Keep it in step with soundboard/core/usage.py and SECURITY.md's
*The anonymous usage count*: anything new the count sends gets a row here too."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QWidget

from soundboard.i18n import _
from soundboard.ui.kit import busy
from soundboard.ui.kit.modalframe import ModalDialog

PRIVACY_URL = ("https://github.com/Onion-Alien/onion-board/blob/main/SECURITY.md"
               "#what-the-app-does-on-the-network")


def rows() -> list[tuple[str, str, str]]:
    """(what, an example of what's sent, why), in the table's order."""
    return [
        (_("Version and updates"), "1.9.27", _("Know which versions need fixes")),
        (_("How the app is used"), _("voice changer, Radio tab"), _("See what to improve")),
        (_("Crashes and freezes"), "crash/1.9.27", _("Find and fix bugs")),
        (_("Your answers, if you give them"), _("heard of it on YouTube"),
         _("Know where people find the app")),
        (_("Mic log, if set-up fails"), "Microphone (USB Audio)", _("Find and fix bugs")),
    ]


class CountDialog(ModalDialog):
    def __init__(self, parent=None):
        super().__init__(parent, _("What Count me in sends"), icon="eye", width=580)
        self.setWindowModality(Qt.WindowModality.NonModal)   # (opened beside Settings)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        f = self.frame
        f.add_text(_("Once a day, anonymous. The count never has your name or device info. "
                     "Where you heard of it and feedback picks only if you give them. "
                     "Switching it off sends one last count with no ID, then nothing."))
        table = QWidget()
        table.setObjectName("modalpoint")   # (no background of its own)
        grid = QGridLayout(table)
        grid.setContentsMargins(0, 2, 0, 2)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        for c, head in enumerate((_("What"), _("Example"), _("Why"))):
            lab = QLabel(head)
            lab.setObjectName("modalpointtitle")
            grid.addWidget(lab, 0, c)
        for r, (what, example, why) in enumerate(rows(), 1):
            top = Qt.AlignmentFlag.AlignTop
            name = QLabel(what)
            name.setWordWrap(True)
            grid.addWidget(name, r, 0, top)
            ex = QLabel(example)
            ex.setObjectName("muted")
            ex.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(ex, r, 1, top)
            reason = QLabel(why)
            reason.setWordWrap(True)   # long languages wrap here, not past 620 px
            grid.addWidget(reason, r, 2, top)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(2, 4)
        f.add_widget(table)
        mic_log = f.add_text(_(
            "If your mic's set-up fails, one log goes too. It has your mic's name and driver "
            "and your PC's audio and security settings. Your user name and PC name are taken "
            "out. This log isn't anonymous like the count."))
        mic_log.setObjectName("muted")
        done = f.add_button(_("Done"), primary=True)
        done.clicked.connect(self.accept)
        # the full list: a quiet button on the footer's left, beside Done
        full = QPushButton(_("The full list"))
        full.setProperty("quiet", True)
        full.setToolTip(PRIVACY_URL)
        full.clicked.connect(lambda: busy.open_url(PRIVACY_URL, window=self))
        f.footer.insertWidget(0, full)
        self.focus_first(done)


def show(parent=None) -> CountDialog:
    """Open it (not modal). Returns it, for tests."""
    dlg = CountDialog(parent)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg
