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
                               QScrollArea, QVBoxLayout, QWidget)

from soundboard.core import errors
from soundboard.i18n import _, ngettext
from soundboard.ui.kit import fit, icons
from soundboard.ui.kit.modalframe import BADGE, GAP, GLYPH, ModalFrame
from soundboard.ui.kit.panel import icon_button

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
    had: str = ""  # a dupe: the name it already has on the board

    def line(self) -> str:
        return f"{self.file}: {self.reason}" if self.reason else self.file


def classify(file: str, e: BaseException | str) -> Skipped:
    name = Path(file).name
    if isinstance(e, AlreadyAdded):
        return Skipped(name, str(e), "dupe", e.name)
    try:
        gone = not Path(file).exists()   # moved or deleted since (the decoder says so in its words)
    except OSError:   # there, but Windows can't look at it
        gone = False
    if gone:
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
            if dupes == 1 and skipped[0].had:   # one sound: which one it matched
                return _("Already in your library as “{name}”", name=skipped[0].had), ""
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
        self.setMinimumWidth(460)
        self.frame = ModalFrame(ngettext("{n} file wasn't added", "{n} files weren't added",
                                         len(skipped)), mascot="bun", close=False)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.frame)

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
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
        # as tall as the list, up to 380 (then it scrolls)
        scroll.setFixedHeight(min(380, body.sizeHint().height()))
        self.frame.body.addWidget(scroll)

        self.btn_copy = icon_button("copy", _("Copy"))
        self.frame.footer.insertWidget(0, self.btn_copy)   # (left: the stretch is after it)
        close = self.frame.add_button(_("Close"), primary=True)
        close.clicked.connect(self.close)
        self.btn_copy.clicked.connect(self.copy)
        fit.watch(self)

    def _group(self, group: str, items: list[Skipped]) -> QWidget:
        """A group as one of the frame's points: its icon in the mascot's column, then
        its name and each file with why under it."""
        box = QWidget()
        box.setObjectName("modalpoint")
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(GAP)
        ic = QLabel()
        ic.setObjectName("modalpointicon")
        ic.setFixedSize(BADGE, BADGE)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icons.set_label_icon(ic, GROUPS[group][0], "accent_text", GLYPH)
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(ic, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addStretch(1)
        holder = QWidget()
        holder.setObjectName("modalpoint")
        holder.setFixedWidth(max(self.frame.lead, BADGE))
        holder.setLayout(column)
        row.addWidget(holder)
        v = QVBoxLayout()
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        h = QLabel(group_title(group))
        h.setObjectName("modalpointtitle")
        v.addWidget(h)
        for s in items:
            one = QVBoxLayout()
            one.setSpacing(0)
            name_lbl = QLabel(s.file)
            name_lbl.setTextFormat(Qt.TextFormat.PlainText)   # file names are the user's text
            name_lbl.setWordWrap(True)
            name_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            why = QLabel(s.reason)
            why.setObjectName("hint")
            why.setTextFormat(Qt.TextFormat.PlainText)
            why.setWordWrap(True)
            why.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            one.addWidget(name_lbl)
            one.addWidget(why)
            v.addLayout(one)
        row.addLayout(v, 1)
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
