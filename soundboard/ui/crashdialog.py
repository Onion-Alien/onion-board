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
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QVBoxLayout)

from soundboard.updates import REPO

ISSUE_URL = f"https://github.com/{REPO}/issues/new"
ISSUE_BODY = ("**What were you doing when it happened?**\n\n\n"
              "**Crash report**\n"
              "<!-- Onion Board copied the report to your clipboard: paste it below "
              "(Ctrl+V). Personal paths are already replaced. -->\n\n")


def issue_url(title: str) -> str:
    t = f"Crash: {title}"[:120]
    return f"{ISSUE_URL}?labels=bug&title={quote(t)}&body={quote(ISSUE_BODY)}"


class CrashDialog(QDialog):
    def __init__(self, rep, log_path: Path | None, parent=None):
        super().__init__(parent)
        self.rep, self.log_path = rep, log_path
        self.setWindowTitle("Onion Board hit a problem")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMinimumSize(560, 420)
        v = QVBoxLayout(self)

        head = QLabel("Sorry — something went wrong." if not rep.fatal
                      else "Sorry — Onion Board couldn't start.")
        f = head.font()
        f.setPointSizeF(f.pointSizeF() * 1.3)
        f.setBold(True)
        head.setFont(f)
        v.addWidget(head)

        what = QLabel(rep.title)
        what.setTextFormat(Qt.PlainText)   # exception text, not markup
        what.setWordWrap(True)
        what.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(what)

        keep = ("The app will close." if rep.fatal else
                "The app is still running, but if something looks wrong, restart it.")
        ask = QLabel(
            f"{keep}<br><br><b>Please send this report to the developer</b> so it can be "
            "fixed: press <i>Report on GitHub</i> and paste it in (it's copied for you), "
            "or <i>Copy report</i> and send it however you like. Nothing is sent "
            "automatically, and your user name and folders are already blanked out.")
        ask.setWordWrap(True)
        v.addWidget(ask)

        self.details = QPlainTextEdit(rep.text)
        self.details.setReadOnly(True)
        self.details.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.details.setFont(mono)
        v.addWidget(self.details, 1)

        self.status = QLabel("")
        self.status.setObjectName("hint")
        v.addWidget(self.status)

        row = QHBoxLayout()
        self.copy_btn = QPushButton("Copy report")
        self.copy_btn.clicked.connect(self.copy)
        self.github_btn = QPushButton("Report on GitHub")
        self.github_btn.setDefault(True)
        self.github_btn.setToolTip("Copies the report and opens a new issue in your browser")
        self.github_btn.clicked.connect(self.open_issue)
        self.folder_btn = QPushButton("Open folder")
        self.folder_btn.setToolTip("The saved report and the app's log")
        self.folder_btn.clicked.connect(self.open_folder)
        self.folder_btn.setEnabled(self._folder() is not None)
        close = QPushButton("Quit" if rep.fatal else "Close")
        close.clicked.connect(self.accept)
        for b in (self.copy_btn, self.github_btn, self.folder_btn):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(close)
        v.addLayout(row)

    def report_text(self) -> str:
        text = self.rep.text
        if self.rep.extra:
            more = "\n".join(f"  {t}" for t in self.rep.extra[:20])
            text += f"\n\nMore errors while this was open\n------------------------------\n{more}"
        return text

    def copy(self):
        QGuiApplication.clipboard().setText(self.report_text())
        self.status.setText("Report copied — paste it into your message (Ctrl+V).")

    def open_issue(self):
        self.copy()
        if QDesktopServices.openUrl(QUrl(issue_url(self.rep.title))):
            self.status.setText("Report copied. Paste it into the issue that just opened "
                                "in your browser (Ctrl+V).")
        else:
            self.status.setText(f"Report copied, but the browser didn't open. Go to "
                                f"{ISSUE_URL} and paste it there.")

    def _folder(self) -> Path | None:
        if self.rep.path is not None:
            return Path(self.rep.path).parent
        return Path(self.log_path).parent if self.log_path else None

    def open_folder(self):
        folder = self._folder()
        if folder is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
