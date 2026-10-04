"""Settings > General > Reset: a two-step guide that puts the parts the user picks
back to how they started, and the Restore points list that undoes it
(soundboard.reset does the work, at the next start-up)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QFrame, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

from soundboard import reset, trash
from soundboard.ui import fit, icons
from soundboard.ui.panel import hint_label, icon_label

# (part, what it does) in the order the guide lists them
OPTIONS = [
    (reset.SETTINGS, "Theme, audio, voice, overlay and privacy options."),
    (reset.HOTKEYS, "The app's hotkeys, back to the defaults."),
    (reset.SOUNDS, "Clears the board. The sounds are kept in the restore point."),
    (reset.BIN, "Empties the bin. It's kept in the restore point."),
    (reset.PROGRAMS, "Forgets Apps tab volumes and hidden programs."),
    (reset.DEVICES, "Forgets your mic, headphones, where your sounds are sent and the "
                     "stream output; the quick setup runs again."),
]


def _heading(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("font-size: 15pt; font-weight: 600;")   # the theme sets fonts in QSS
    lbl.setWordWrap(True)
    return lbl


class ResetGuide(QDialog):
    """Pick → check → reset and restart. `mw` is the MainWindow (restart_app)."""

    def __init__(self, mw, parent=None):
        super().__init__(parent or mw)
        fit.watch(self)
        self.mw = mw
        self.setWindowTitle("Reset")
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        # two pages, only one shown: a hidden one takes no room, so each step is as
        # tall as it needs (a QStackedWidget is as tall as its tallest page)
        self.pages = [self._pick_page(), self._check_page()]
        for p in self.pages:
            lay.addWidget(p, 1)
        self.show_page(0)
        self._update()

    def page(self) -> int:
        return next(i for i, p in enumerate(self.pages) if not p.isHidden())

    def show_page(self, i: int):
        for n, p in enumerate(self.pages):
            p.setHidden(n != i)
        if self.isVisible():
            self.resize(self.width(), fit.needed_height(self, self.width()))

    # ------------------------------------------------------------------ step 1
    def _pick_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        v.addWidget(_heading("What do you want to reset?"))
        v.addWidget(hint_label("Pick only what's giving you trouble. Everything else stays "
                               "as it is."))
        self.boxes: dict[str, QCheckBox] = {}
        for part, hint in OPTIONS:
            row = QFrame()
            row.setObjectName("setcard")
            rv = QVBoxLayout(row)
            rv.setContentsMargins(12, 8, 12, 9)
            rv.setSpacing(2)
            box = QCheckBox(reset.NAMES[part])
            f = QFont(box.font())
            f.setBold(True)
            box.setFont(f)
            box.toggled.connect(self._update)
            rv.addWidget(box)
            h = hint_label(hint)
            h.setContentsMargins(24, 0, 0, 0)
            rv.addWidget(h)
            if part == reset.HOTKEYS:
                self.sound_keys = QCheckBox("Clear sound hotkeys too")
                self.sound_keys.toggled.connect(self._update)
                wrap = QHBoxLayout()
                wrap.setContentsMargins(24, 2, 0, 0)
                wrap.addWidget(self.sound_keys)
                rv.addLayout(wrap)
            self.boxes[part] = box
            v.addWidget(row)
        safe = QHBoxLayout()
        safe.setSpacing(6)
        safe.addWidget(icon_label("shield"))
        safe.addWidget(hint_label("A restore point is saved first, so you can undo this."), 1)
        v.addSpacing(4)
        v.addLayout(safe)
        v.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.btn_next = QPushButton("Next")
        self.btn_next.setObjectName("primary")
        self.btn_next.setDefault(True)
        self.btn_next.clicked.connect(self._to_check)
        row.addWidget(cancel)
        row.addWidget(self.btn_next)
        v.addLayout(row)
        return w

    def parts(self) -> list[str]:
        out = [p for p, b in self.boxes.items() if b.isChecked()]
        if self.boxes[reset.HOTKEYS].isChecked() and self.sound_keys.isChecked():
            out.append(reset.SOUND_KEYS)
        return [p for p in reset.PARTS if p in out]

    def _update(self, *_):
        hk = self.boxes[reset.HOTKEYS].isChecked()
        self.sound_keys.setVisible(hk)
        self.btn_next.setEnabled(bool(self.parts()))

    # ------------------------------------------------------------------ step 2
    def _check_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        v.addWidget(_heading("Ready to reset"))
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        card = QFrame()
        card.setObjectName("setcard")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(14, 10, 14, 12)
        cv.addWidget(self.summary)
        v.addWidget(card)
        v.addWidget(hint_label("Onion Board restarts to finish, which takes a few seconds. "
                               "To undo it, open Settings › General › Restore points."))
        v.addStretch(1)
        row = QHBoxLayout()
        back = QPushButton("Back")
        back.clicked.connect(lambda: self.show_page(0))
        row.addWidget(back)
        row.addStretch(1)
        self.btn_go = QPushButton("Reset and restart")
        self.btn_go.setObjectName("danger")
        self.btn_go.clicked.connect(self._go)
        row.addWidget(self.btn_go)
        v.addLayout(row)
        return w

    def _to_check(self):
        lines = {reset.SETTINGS: "Settings go back to the defaults",
                 reset.HOTKEYS: "App hotkeys go back to the defaults",
                 reset.SOUND_KEYS: "Every sound's hotkey is cleared",
                 reset.SOUNDS: "Every sound comes off the board",
                 reset.BIN: "Recently deleted is emptied",
                 reset.PROGRAMS: "Program volumes are forgotten",
                 reset.DEVICES: "Devices are forgotten; the quick setup runs again"}
        self.summary.setText("".join(f"<p style='margin:4px 0'>•&nbsp; {lines[p]}</p>"
                                     for p in self.parts()))
        self.show_page(1)
        self.btn_go.setFocus()

    def _go(self):
        reset.schedule_reset(self.parts())
        self.accept()
        QTimer.singleShot(0, self.mw.restart_app)   # once this window's loop is done


class RestorePoints(QDialog):
    """The saved restore points, newest first: Restore (restarts) or Delete."""

    def __init__(self, mw, parent=None):
        super().__init__(parent or mw)
        fit.watch(self)
        self.mw = mw
        self.setWindowTitle("Restore points")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        lay.addWidget(_heading("Restore points"))
        lay.addWidget(hint_label(
            f"One is saved every time you reset something (the last {reset.MAX_POINTS} are "
            "kept). Restoring puts back your settings, hotkeys and sounds as they were. "
            "Sounds you've added since are kept."))
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setMinimumSize(420, 200)
        self.list.itemSelectionChanged.connect(self._update)
        self.list.itemDoubleClicked.connect(lambda _i: self.restore())
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.btn_delete = QPushButton("Delete")
        icons.set_icon(self.btn_delete, "trash", "danger_text")
        self.btn_delete.clicked.connect(self.delete)
        row.addWidget(self.btn_delete)
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        self.btn_restore = QPushButton("Restore")
        self.btn_restore.setObjectName("primary")
        self.btn_restore.clicked.connect(self.restore)
        row.addWidget(self.btn_restore)
        lay.addLayout(row)
        self.fill()

    def fill(self):
        self.list.clear()
        for p in reset.points():
            li = QListWidgetItem(f"{p.label}  ·  {trash.ago(p.when)}\n{p.describe()}")
            li.setData(Qt.UserRole, p.id)
            self.list.addItem(li)
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            li = QListWidgetItem("No restore points yet. One is saved every time you reset "
                                 "something.")
            li.setFlags(Qt.NoItemFlags)
            self.list.addItem(li)
        self._update()

    def _picked(self) -> reset.Point | None:
        li = self.list.currentItem()
        pid = li.data(Qt.UserRole) if li is not None and li.isSelected() else None
        return next((p for p in reset.points() if p.id == pid), None) if pid else None

    def _update(self):
        on = self._picked() is not None
        self.btn_restore.setEnabled(on)
        self.btn_delete.setEnabled(on)

    def restore(self):
        p = self._picked()
        if p is None:
            return
        if QMessageBox.question(
                self, "Restore",
                f"Put things back the way they were {trash.ago(p.when)}?\n\n"
                "Onion Board restarts to do it. A new restore point is saved first, so "
                "this can be undone too.") != QMessageBox.Yes:
            return
        reset.schedule_restore(p.id)
        self.accept()
        QTimer.singleShot(0, self.mw.restart_app)

    def delete(self):
        p = self._picked()
        if p is None:
            return
        if QMessageBox.question(
                self, "Delete restore point",
                "Delete this restore point? You won't be able to go back to it. Sounds "
                "kept in it go to the Windows Recycle Bin.") != QMessageBox.Yes:
            return
        reset.delete_point(p.id)
        self.fill()
