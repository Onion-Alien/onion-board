"""What happened to the files someone added: the toast at the end, and *See why*.

An import ends in one toast that says how it went ("Added 10 sounds · 2 skipped")
instead of a warning box to click away. Files that weren't added are sorted into a
few plain groups (already in your library, couldn't be opened, not a sound), listed
in a small window that *See why* opens, with each file's own reason and a copy button.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from soundboard.core import errors
from soundboard.i18n import _, ngettext
from soundboard.ui import fit, icons

LONG = 140   # a reason longer than this is a tool's log: say it plainly instead

# group -> (icon, its colour token); also the order they're listed in
GROUPS = {
    "dupe": ("info", "accent"),
    "unreadable": ("warn", "warn_text"),
    "not_sound": ("alert", "error_text"),
}


def group_title(group: str) -> str:
    return {"dupe": _("Already in your library"),
            "unreadable": _("Couldn't be opened"),
            "not_sound": _("Not a sound we can play")}[group]


class AlreadyAdded(RuntimeError):
    """The same sound (by its fingerprint) is already on the board."""

    def __init__(self, name: str):
        super().__init__(_("already in your library as “{name}”", name=name))
        self.name = name


@dataclass
class Skipped:
    file: str      # the name shown (a file, or "pack.zip → inner.wav")
    reason: str    # plain words
    group: str     # a GROUPS key

    def line(self) -> str:
        return f"{self.file}: {self.reason}" if self.reason else self.file


def classify(file: str, e: BaseException | str) -> Skipped:
    name = Path(file).name
    if isinstance(e, AlreadyAdded):
        return Skipped(name, str(e), "dupe")
    if not Path(file).exists():   # moved or deleted since (the decoder says so in its words)
        return Skipped(name, _("The file isn't there any more."), "unreadable")
    if isinstance(e, OSError):    # locked, no permission, no room
        return Skipped(name, errors.plain(e), "unreadable")
    reason = errors.plain(e)
    if len(reason) > LONG or "\n" in reason:   # a decoder's log, not words for people
        reason = _("It isn't a sound file that can be read, or it's damaged.")
    return Skipped(name, reason, "not_sound")


def summary(added: int, skipped: list[Skipped]) -> tuple[str, str]:
    """The toast's text and kind for an import that's over."""
    k = len(skipped)
    dupes = sum(s.group == "dupe" for s in skipped)
    dupes_only = k and dupes == k
    if added and not k:
        return ngettext("✓ Added {n} sound", "✓ Added {n} sounds", added), "ok"
    if added:
        return (_("{added} · {skipped}",
                  added=ngettext("Added {n} sound", "Added {n} sounds", added),
                  skipped=ngettext("{n} skipped", "{n} skipped", k)),
                "" if dupes_only else "warn")
    if dupes:
        already = (_("That sound is already in your library") if dupes == 1 else
                   ngettext("{n} sound is already in your library",
                            "{n} sounds are already in your library", dupes))
        if dupes_only:
            return already, ""
        return (_("{added} · {skipped}", added=already,
                  skipped=ngettext("{n} skipped", "{n} skipped", k - dupes)), "warn")
    return ngettext("Couldn't add {n} file", "Couldn't add {n} files", k), "error"


class SkippedDialog(QDialog):
    """The files that weren't added, grouped, each with why. Not modal: sounds and
    hotkeys keep working while it's open."""
    MAX_ROWS = 200

    def __init__(self, skipped: list[Skipped], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(_("Files not added"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMaximumWidth(620)
        self.skipped = skipped
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        title = QLabel(ngettext("{n} file wasn't added", "{n} files weren't added",
                                len(skipped)))
        title.setObjectName("title")
        f = title.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * 1.3)
        title.setFont(f)
        root.addWidget(title)

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        shown = 0
        for group in GROUPS:
            items = [s for s in skipped if s.group == group]
            if not items:
                continue
            lay.addWidget(self._group(group, items[:max(0, self.MAX_ROWS - shown)]))
            shown += len(items)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body)
        scroll.setMinimumWidth(420)
        # as tall as the list, up to 380 (then it scrolls)
        scroll.setFixedHeight(min(380, body.sizeHint().height()))
        root.addWidget(scroll)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.btn_copy = QPushButton()
        self.btn_copy.setProperty("quiet", True)
        self.btn_copy.setFixedSize(32, 32)
        self.btn_copy.setAccessibleName(_("Copy"))
        icons.set_icon(self.btn_copy, "copy")
        self.btn_copy.clicked.connect(self.copy)
        foot.addWidget(self.btn_copy)
        foot.addStretch(1)
        close = QPushButton(_("Close"))
        close.setObjectName("primary")
        close.setDefault(True)
        close.clicked.connect(self.close)
        foot.addWidget(close)
        root.addLayout(foot)
        fit.watch(self)

    def _group(self, group: str, items: list[Skipped]) -> QFrame:
        box = QFrame()
        box.setObjectName("card")
        v = QVBoxLayout(box)
        v.setContentsMargins(14, 12, 14, 14)
        v.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        ic = QLabel()
        name, tone = GROUPS[group]
        icons.set_label_icon(ic, name, tone, 18)
        head.addWidget(ic)
        h = QLabel(group_title(group))
        h.setObjectName("section")
        head.addWidget(h)
        head.addStretch(1)
        v.addLayout(head)
        for s in items:
            row = QVBoxLayout()
            row.setSpacing(0)
            name_lbl = QLabel(s.file)
            name_lbl.setTextFormat(Qt.TextFormat.PlainText)   # file names are the user's text
            name_lbl.setWordWrap(True)
            name_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            why = QLabel(s.reason)
            why.setObjectName("hint")
            why.setTextFormat(Qt.TextFormat.PlainText)
            why.setWordWrap(True)
            why.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row.addWidget(name_lbl)
            row.addWidget(why)
            v.addLayout(row)
        return box

    def text(self) -> str:
        out = []
        for group in GROUPS:
            items = [s for s in self.skipped if s.group == group]
            if items:
                out.append(group_title(group))
                out += [f"  {s.line()}" for s in items]
        return "\n".join(out)

    def copy(self):
        QApplication.clipboard().setText(self.text())
        icons.set_icon(self.btn_copy, "check", "ok_text")
        self.btn_copy.setAccessibleName(_("✓ Copied"))
        QTimer.singleShot(1500, self.btn_copy, lambda: (
            icons.set_icon(self.btn_copy, "copy"), self.btn_copy.setAccessibleName(_("Copy"))))
