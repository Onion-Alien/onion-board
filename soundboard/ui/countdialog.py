"""*What Count me in sends*: the eye button beside Settings' Count me in opens this
small table (what, an example, why), so the setting itself stays one line and the
whole list is one click away. Keep it in step with soundboard/usage.py and the
SECURITY.md row: anything new the count sends gets a row here too."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from soundboard import theme
from soundboard.i18n import _
from soundboard.ui import busy, fit

PRIVACY_URL = ("https://github.com/Onion-Alien/onion-board/blob/main/SECURITY.md"
               "#what-the-app-does-on-the-network")
GOATCOUNTER_PRIVACY = "https://www.goatcounter.com/help/privacy"


def rows() -> list[tuple[str, str, str]]:
    """(what, an example of what's sent, why), in the table's order."""
    return [
        (_("App version"), "1.9.27", _("Know which versions people still use")),
        (_("Tabs and features used"), "voice-changer", _("See what to improve")),
        (_("First steps"), "played-sound", _("See where new people get stuck")),
        (_("How it's set up"), "route/mic, lang/de", _("Test the setups people really use")),
        (_("Rough numbers"), "sounds/11-50", _("Know how big boards get")),
        (_("Crashes and freezes"), "crash/1.9.27", _("Find and fix bugs")),
        (_("Updates and uninstalls"), "update-now", _("Check that updates work")),
        (_("Where you heard of it"), "youtube", _("Know where people find the app")),
        (_("Feedback picks"), "improve/looks", _("Know what to work on")),
        (_("A random ID"), "3f9a1c…", _("Count each person once")),
    ]


class CountDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        fit.watch(self)   # grows to fit its text (ui/fit.py)
        self.setWindowTitle(_("What Count me in sends"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 14)
        hint = QLabel(_("Once a day, anonymous. Never your name, IP address or device "
                        "info. Where you heard of it and feedback picks only if you give "
                        "them. Switching it off sends one last count with no ID, then "
                        "nothing."))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        for c, head in enumerate((_("What"), _("Example"), _("Why"))):
            lab = QLabel(head)
            f = lab.font()
            f.setBold(True)
            lab.setFont(f)
            grid.addWidget(lab, 0, c)
        for r, (what, example, why) in enumerate(rows(), 1):
            top = Qt.AlignmentFlag.AlignTop
            grid.addWidget(QLabel(what), r, 0, top)
            ex = QLabel(example)
            ex.setObjectName("hint")
            ex.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(ex, r, 1, top)
            reason = QLabel(why)
            reason.setWordWrap(True)   # long languages wrap here, not past 620 px
            grid.addWidget(reason, r, 2, top)
        grid.setColumnStretch(2, 1)
        v.addSpacing(4)
        v.addLayout(grid)
        style = f'style="color: {theme.T["accent"]};"'
        links = QLabel(f'<a href="{PRIVACY_URL}" {style}>{_("The full list")}</a> · '
                       f'<a href="{GOATCOUNTER_PRIVACY}" {style}>'
                       f'{_("GoatCounter privacy policy")}</a>')
        links.linkActivated.connect(lambda url: busy.open_url(url, window=self))
        v.addSpacing(6)
        v.addWidget(links)
        row = QHBoxLayout()
        done = QPushButton(_("Done"))
        done.setDefault(True)
        done.clicked.connect(self.accept)
        row.addWidget(done)
        row.addStretch(1)
        v.addSpacing(6)
        v.addLayout(row)
        self.setMinimumWidth(540)   # English on one line a row; longer languages wrap Why
        self.setMaximumWidth(620)   # DESIGN.md: dialogs about 620 px at most
        # as tall as the rows at that width (wrapped labels first guess a narrower one)
        self.resize(540, self.layout().totalHeightForWidth(540))


def show(parent=None) -> CountDialog:
    """Open it (not modal). Returns it, for tests."""
    dlg = CountDialog(parent)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg
