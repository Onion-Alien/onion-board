"""The "Onion Board hit a problem" dialog (see applog.py).

Shows what went wrong in plain words, the full report (scrubbed of personal paths)
and asks the user to send it to the developer: *Copy report*, *Report on GitHub*
(copies it too, then opens a new-issue page in their browser — nothing is posted
for them) and *Open folder* for the saved report and the log."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QGuiApplication
from PySide6.QtWidgets import QDialog, QPlainTextEdit, QPushButton
import shiboken6

from soundboard.ui.kit.modalframe import ModalDialog
from soundboard.ui.kit.panel import icon_button
from soundboard.core.updates import REPO
from soundboard.i18n import _

ISSUE_URL = f"https://github.com/{REPO}/issues/new"
ISSUE_BODY = ("**What were you doing when it happened?**\n\n\n"
              "**Crash report**\n"
              "<!-- Onion Board copied the report to your clipboard: paste it below "
              "(Ctrl+V). Personal paths are already replaced. -->\n\n")


def issue_url(title: str) -> str:
    t = f"Crash: {title}"[:120]
    return f"{ISSUE_URL}?labels=bug&title={quote(t)}&body={quote(ISSUE_BODY)}"


class CrashDialog(ModalDialog):
    """A small modal on the shared frame (kit/modalframe.py); shown modeless (show) while
    the app runs on, modal (exec) when it couldn't start."""
    KEEP_OPEN = True   # a click outside doesn't close it: it would lose work
    def __init__(self, rep, log_path: Path | None, parent=None):
        super().__init__(parent, _("Sorry, something went wrong.") if not rep.fatal
                         else _("Sorry, Onion Board couldn't start."),
                         icon="alert", tone="error", width=560)
        self.setWindowModality(Qt.WindowModality.NonModal)   # (exec makes it modal itself)
        self.rep, self.log_path = rep, log_path
        self.setWindowTitle(_("Onion Board hit a problem"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        f = self.frame
        # what went wrong, under the title: the exception's own words (plain text, never
        # markup), selectable to copy
        f.subtitle.setText(rep.title)
        f.subtitle.setVisible(True)
        f.subtitle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        keep = (_("The app will close.") if rep.fatal else
                _("The app is still running, but if something looks wrong, restart it."))
        f.add_text(
            _("{keep}<br><br><b>Please send this report to the developer</b> so it can be fixed: "
              "press <i>Report on GitHub</i> and paste it in (it's copied for you), or <i>Copy "
              "report</i> and send it however you like. Nothing is sent automatically, and your "
              "user name and folders are already blanked out.", keep=keep), rich=True)

        # the report itself: there to read, folded away so the box isn't mostly a big
        # grey panel of code
        self.details = QPlainTextEdit(rep.text)
        self.details.setReadOnly(True)
        self.details.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.details.setFont(mono)
        self.details.setMinimumHeight(200)
        self.details.hide()
        f.add_widget(self.details)

        self.status = f.add_text("")
        self.status.setObjectName("muted")
        self.status.hide()

        self.github_btn = f.add_button(_("Report on GitHub"), primary=True)
        self.copy_btn = f.add_button(_("Copy report"))
        f.add_button(_("Quit") if rep.fatal else _("Close")).clicked.connect(self.accept)
        # on the footer's left: show the report, and the folder it's saved in
        self.show_btn = QPushButton(_("Show the report"))
        self.show_btn.setProperty("quiet", True)
        f.footer.insertWidget(0, self.show_btn)
        self.show_btn.clicked.connect(lambda: self._show_details(self.details.isHidden()))
        self.folder_btn = icon_button("folder", _("Open folder"))
        # The name says what it does; the tooltip also says what's in there.
        self.folder_btn.setToolTip(_("Open folder") + "\n"
                                   + _("The saved report and the app's log"))
        self.folder_btn.clicked.connect(self.open_folder)
        self.folder_btn.setEnabled(self._folder() is not None)
        f.footer.insertWidget(1, self.folder_btn)
        self.github_btn.setToolTip(_("Copies the report and opens a new issue in your browser"))
        self.github_btn.clicked.connect(self.open_issue)
        self.copy_btn.clicked.connect(self.copy)
        self.focus_first(self.github_btn)

    def _say(self, text: str):
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def _show_details(self, on: bool):
        self.details.setVisible(on)
        self.show_btn.setText(_("Hide the report") if on else _("Show the report"))
        self.adjustSize()

    def report_text(self) -> str:
        text = self.rep.text
        if self.rep.extra:
            more = "\n".join(f"  {t}" for t in self.rep.extra[:20])
            text += f"\n\nMore errors while this was open\n------------------------------\n{more}"
        return text

    def copy(self):
        QGuiApplication.clipboard().setText(self.report_text())
        self._say(_("Report copied: paste it into your message (Ctrl+V)."))

    def open_issue(self):
        self.copy()
        if QDesktopServices.openUrl(QUrl(issue_url(self.rep.title))):
            self._say(_("Report copied. Paste it into the issue that just opened in "
                        "your browser (Ctrl+V)."))
        else:
            self._say(_("Report copied, but the browser didn't open. Go to {issue_url} "
                        "and paste it there.", issue_url=ISSUE_URL))

    def _folder(self) -> Path | None:
        if self.rep.path is not None:
            return Path(self.rep.path).parent
        return Path(self.log_path).parent if self.log_path else None

    def open_folder(self):
        folder = self._folder()
        if folder is None:
            return
        if QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            self._say(_("Opened the folder with the log in it."))
        else:
            self._say(_("Couldn't open the folder. It's here: {folder}", folder=folder))


def free_dialog(dlg: QDialog):
    """Delete a modal dialog once its exec() has returned. Parented to the window and
    never freed, every closed copy stayed alive and made each theme change slower.
    A crash report opened over it is moved to the dialog's parent's window first, so it
    stays (Settings is a page inside the window, not a window of its own).
    Already gone (its window was freed first, before a deferred call got here): done."""
    if not shiboken6.isValid(dlg):
        return
    rehome_crash_reports(dlg)
    shiboken6.delete(dlg)


def rehome_crash_reports(dlg: QDialog):
    """Crash reports opened over `dlg` move to its parent's window and stay up: it's
    being freed, or kept hidden to be opened again (MainWindow's Settings, Edit sound)."""
    parent = dlg.parentWidget()
    parent = parent.window() if parent is not None else None
    for c in dlg.findChildren(CrashDialog):
        c.setParent(parent, c.windowFlags())
        c.show()
