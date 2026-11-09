"""Settings > General > Reset: a two-step guide that puts the parts the user picks
back to how they started, and the Restore points list that undoes it
(soundboard.core.reset does the work, at the next start-up)."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QFrame, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout, QWidget)

from soundboard.core import reset, trash
from soundboard.ui.kit import fit, icons, modalframe
from soundboard.ui.kit.panel import hint_label, icon_label
from soundboard.i18n import _
from soundboard.ui.setup.wizardkit import SMALL_W, aligned, framed, indent, rich

# (part, what it does) in the order the guide lists them
OPTIONS = [
    (reset.SETTINGS, _("Theme, audio, voice, overlay and privacy options.")),
    (reset.HOTKEYS, _("The app's hotkeys, back to the defaults.")),
    (reset.SOUNDS, _("Clears the board. The sounds are kept in the restore point.")),
    (reset.BIN, _("Empties the bin. It's kept in the restore point.")),
    (reset.PROGRAMS, _("Forgets Apps tab volumes and hidden programs.")),
    (reset.DEVICES, _("Forgets your mic, headphones, where your sounds are sent and the "
                      "stream output; the quick setup runs again.")),
]


def _page_widget(frame) -> tuple[QWidget, QVBoxLayout]:
    """A step's page in the frame's body, its words on the title's edge."""
    w = QWidget()
    w.setObjectName("modalpoint")   # (see-through: the frame's own surface)
    v = QVBoxLayout(w)
    v.setContentsMargins(indent(frame), 0, 0, 0)
    v.setSpacing(10)
    return w, v


class ResetGuide(QDialog):
    """Pick → check → reset and restart. `mw` is the MainWindow (restart_app)."""

    def __init__(self, mw, parent=None):
        super().__init__(parent or mw)
        fit.watch(self)
        self.mw = mw
        self.setWindowTitle(_("Reset"))
        self.setMinimumWidth(SMALL_W)
        self.frame = framed(self, "")
        # two pages, only one shown: a hidden one takes no room, so each step is as
        # tall as it needs (a QStackedWidget is as tall as its tallest page)
        self.pages = [self._pick_page(), self._check_page()]
        for p in self.pages:
            self.frame.body.addWidget(p, 1)
        self.show_page(0)
        self._update()

    def page(self) -> int:
        return next(i for i, p in enumerate(self.pages) if not p.isHidden())

    def show_page(self, i: int):
        for n, p in enumerate(self.pages):
            p.setHidden(n != i)
        # each step's question in the frame's header (the step's own words under it)
        self.frame.heading.setText(_("What do you want to reset?") if i == 0
                                   else _("Ready to reset"))
        sub = (_("Pick only what's giving you trouble. Everything else stays as it is.")
               if i == 0 else "")
        self.frame.subtitle.setText(sub)
        self.frame.subtitle.setHidden(not sub)
        if self.isVisible():
            self.resize(self.width(), fit.needed_height(self, self.width()))

    # ------------------------------------------------------------------ step 1
    def _pick_page(self) -> QWidget:
        w, v = _page_widget(self.frame)
        self.boxes: dict[str, QCheckBox] = {}
        for part, hint in OPTIONS:
            row = QFrame()
            row.setObjectName("setcard")
            rv = QVBoxLayout(row)
            rv.setContentsMargins(12, 8, 12, 9)
            rv.setSpacing(2)
            box = QCheckBox(reset.part_name(part))
            f = QFont(box.font())
            f.setBold(True)
            box.setFont(f)
            box.toggled.connect(self._update)
            rv.addWidget(box)
            h = hint_label(hint)
            h.setContentsMargins(24, 0, 0, 0)
            rv.addWidget(h)
            if part == reset.HOTKEYS:
                self.sound_keys = QCheckBox(_("Clear sound hotkeys too"))
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
        safe.addWidget(hint_label(_("A restore point is saved first, so you can undo this.")), 1)
        v.addSpacing(4)
        v.addLayout(safe)
        v.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton(_("Cancel"))
        cancel.clicked.connect(self.reject)
        self.btn_next = QPushButton(_("Next"))
        self.btn_next.setObjectName("primary")
        self.btn_next.setDefault(True)
        self.btn_next.clicked.connect(self._to_check)
        row.addWidget(self.btn_next)   # the main button first
        row.addWidget(cancel)
        v.addLayout(row)
        return w

    def parts(self) -> list[str]:
        out = [p for p, b in self.boxes.items() if b.isChecked()]
        if self.boxes[reset.HOTKEYS].isChecked() and self.sound_keys.isChecked():
            out.append(reset.SOUND_KEYS)
        return [p for p in reset.PARTS if p in out]

    def _update(self, *__):
        hk = self.boxes[reset.HOTKEYS].isChecked()
        self.sound_keys.setVisible(hk)
        self.btn_next.setEnabled(bool(self.parts()))

    # ------------------------------------------------------------------ step 2
    def _check_page(self) -> QWidget:
        w, v = _page_widget(self.frame)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        card = QFrame()
        card.setObjectName("setcard")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(14, 10, 14, 12)
        cv.addWidget(self.summary)
        v.addWidget(card)
        v.addWidget(hint_label(_("Onion Board restarts to finish, which takes a few seconds. To "
                                 "undo it, open Settings › General › Restore points.")))
        v.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)   # the main button first, then Back (as step 1's Next, Cancel)
        self.btn_go = QPushButton(_("Reset and restart"))
        self.btn_go.setObjectName("danger")
        self.btn_go.clicked.connect(self._go)
        row.addWidget(self.btn_go)
        back = QPushButton(_("Back"))
        back.clicked.connect(lambda: self.show_page(0))
        row.addWidget(back)
        v.addLayout(row)
        return w

    def _to_check(self):
        lines = {reset.SETTINGS: _("Settings go back to the defaults"),
                 reset.HOTKEYS: _("App hotkeys go back to the defaults"),
                 reset.SOUND_KEYS: _("Every sound's hotkey is cleared"),
                 reset.SOUNDS: _("Every sound comes off the board"),
                 reset.BIN: _("Recently deleted is emptied"),
                 reset.PROGRAMS: _("Program volumes are forgotten"),
                 reset.DEVICES: _("Devices are forgotten; the quick setup runs again")}
        self.summary.setText("".join(f"<p style='margin:4px 0'>•&nbsp; {lines[p]}</p>"
                                     for p in self.parts()))
        self.show_page(1)
        self.btn_go.setFocus()

    def _go(self):
        reset.schedule_reset(self.parts())
        self.accept()
        QTimer.singleShot(0, self.mw.restart_app)   # once this window's loop is done


def _point_row(title: str, meta: str) -> QWidget:
    """One restore point in the list: a history icon, its title, and what it holds and
    when in muted text under it."""
    w = QWidget()
    w.setObjectName("pointrow")
    w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)   # the item selects
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 8, 0, 8)   # (the list's rows are 12 px in already: pointlist)
    h.setSpacing(12)
    h.addWidget(icon_label("history"), 0, Qt.AlignmentFlag.AlignVCenter)
    v = QVBoxLayout()
    v.setSpacing(2)
    name = QLabel(title)
    name.setObjectName("pointtitle")
    v.addWidget(name)
    sub = hint_label(meta)
    sub.setWordWrap(False)
    v.addWidget(sub)
    h.addLayout(v, 1)
    return w


class RestorePoints(QDialog):
    """The saved restore points, newest first: Restore (restarts) or Delete."""

    def __init__(self, mw, parent=None):
        super().__init__(parent or mw)
        fit.watch(self)
        self.mw = mw
        self.setWindowTitle(_("Restore points"))
        self.setMinimumWidth(SMALL_W)
        f = framed(self, _("Restore points"))
        rich(f, _("One is saved every time you reset something or update the app (the last "
                  "{max_points} are kept). "
                  "Restoring puts back your settings, hotkeys and sounds as they were. Sounds "
                  "you've added since are kept.", max_points=reset.MAX_POINTS), hint=True)
        self.list = QListWidget()
        self.list.setObjectName("pointlist")
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setWordWrap(True)   # (the empty list's line, at the frame's width)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)   # all fit
        self.list.itemSelectionChanged.connect(self._update)
        self.list.itemDoubleClicked.connect(lambda _i: self.restore())
        aligned(f, self.list)
        # Delete: a quiet danger button under the list, by what it removes
        self.btn_delete = QPushButton(_("Delete"))
        self.btn_delete.setObjectName("danger")
        self.btn_delete.setProperty("quiet", True)
        self.btn_delete.setAutoDefault(False)
        icons.set_icon(self.btn_delete, "trash", "danger_text")
        self.btn_delete.clicked.connect(self.delete)
        under = QHBoxLayout()
        under.addWidget(self.btn_delete)
        under.addStretch(1)
        aligned(f, under)
        self.btn_restore = f.add_button(_("Restore"), primary=True)   # Enter restores
        self.btn_restore.clicked.connect(self.restore)
        f.add_button(_("Close")).clicked.connect(self.reject)
        self.fill()

    def fill(self):
        self.list.clear()
        for p in reset.points():
            meta = f"{p.describe()}  ·  {trash.ago(p.when)}"
            li = QListWidgetItem()
            li.setData(Qt.ItemDataRole.UserRole, p.id)
            li.setData(Qt.ItemDataRole.AccessibleTextRole, f"{p.title}, {meta}")
            row = _point_row(p.title, meta)
            li.setSizeHint(row.sizeHint())
            self.list.addItem(li)
            self.list.setItemWidget(li, row)
        any_points = bool(self.list.count())
        self.btn_delete.setVisible(any_points)   # red with nothing to delete read as live
        if any_points:
            self.list.setCurrentRow(0)
        else:
            li = QListWidgetItem(_("No restore points yet. One is saved every time you reset "
                                   "something."))
            li.setFlags(Qt.ItemFlag.NoItemFlags)
            li.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            li.setSizeHint(QSize(0, 64))
            self.list.addItem(li)
        # as tall as its rows (all MAX_POINTS fit), never an empty box under them
        rows = sum(self.list.sizeHintForRow(i) for i in range(self.list.count()))
        self.list.setFixedHeight(rows + 2 * self.list.frameWidth() + 2 * 6)   # + its padding
        self._update()

    def _picked(self) -> reset.Point | None:
        li = self.list.currentItem()
        pid = li.data(Qt.ItemDataRole.UserRole) if li is not None and li.isSelected() else None
        return next((p for p in reset.points() if p.id == pid), None) if pid else None

    def _update(self):
        on = self._picked() is not None
        self.btn_restore.setEnabled(on)
        self.btn_delete.setEnabled(on)

    def restore(self):
        p = self._picked()
        if p is None:
            return
        if not modalframe.confirm(
                self, _("Restore"),
                _("Put things back the way they were {ago}?\n\nOnion Board restarts to do it. A "
                  "new restore point is saved first, so this can be undone too.",
                  ago=trash.ago(p.when)), _("Restore")):
            return
        reset.schedule_restore(p.id)
        self.accept()
        QTimer.singleShot(0, self.mw.restart_app)

    def delete(self):
        p = self._picked()
        if p is None:
            return
        if not modalframe.confirm(
                self, _("Delete restore point"),
                _("Delete this restore point? You won't be able to go back to it. Sounds kept in "
                  "it go to the Windows Recycle Bin."), _("Delete"), danger=True):
            return
        reset.delete_point(p.id)
        self.fill()
